"""
意图识别引擎 - 大模型驱动的自然语言到投放操作的转换
支持操作安全分级（L0自动执行 / L1一键确认 / L2人工审核 / L3仅建议）

设计原则：服务启动与大模型集成解耦
- 规则引擎：始终可用，无需 LLM
- LLM 增强：配置 API Key 后自动启用，提升解析准确率
- 优雅降级：LLM 不可用时自动回退到规则引擎
"""
import json
import re
import asyncio
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.sys import User
from app.models.data import AggUADaily, Alert
from app.models.intent import IntentExecution, ActionLog
from app.config import settings
from app.services.llm import get_llm_router, is_llm_available


# 意图分类字典 - 规则引擎使用
INTENT_CLASSIFICATION = {
    "campaign.pause": ["暂停", "停掉", "停止", "下线", "pause", "stop", "下线"],
    "campaign.resume": ["恢复", "开启", "启动", "resume", "start"],
    "campaign.budget_adjust": ["调整预算", "加预算", "降预算", "改预算", "budget", "预算"],
    "campaign.bid_adjust": ["调整出价", "提价", "降价", "出价", "bid"],
    "campaign.optimize_batch": ["优化", "规整", "整理", "optimize", "把roi低的"],
    "creative.rotate": ["换素材", "素材轮换", "更新素材", "creative"],
    "alert.review": ["查看告警", "异常检查", "check alerts"],
    "report.generate": ["生成报告", "导出数据", "报表", "report"],
}

# 风险等级映射
RISK_LEVEL_MAP = {
    "campaign.pause": "L1",           # 一键确认
    "campaign.resume": "L1",          # 一键确认
    "campaign.budget_adjust": "L1",   # 一键确认（调整幅度大的升级为L2）
    "campaign.bid_adjust": "L2",      # 人工审核
    "campaign.optimize_batch": "L1",  # 批量操作
    "creative.rotate": "L0",          # 自动执行（素材轮换相对安全）
    "alert.review": "L0",             # 只读，自动执行
    "report.generate": "L0",          # 只读，自动执行
}


class IntentEngine:
    def __init__(self, db: Session, user: User, app_id: int):
        self.db = db
        self.user = user
        self.app_id = app_id
        self._llm_router = None
        self._llm_enabled = False
        self._init_llm_router()

    def _init_llm_router(self):
        """初始化 LLM 路由（懒加载，失败时静默降级）"""
        try:
            config = settings.get_llm_providers_config()
            self._llm_router = get_llm_router(config)
            self._llm_enabled = is_llm_available()
        except Exception:
            # LLM 初始化失败，使用纯规则引擎模式
            self._llm_enabled = False
            self._llm_router = None

    def is_llm_enabled(self) -> bool:
        """检查 LLM 增强模式是否可用"""
        return self._llm_enabled and self._llm_router is not None

    def parse(self, text: str, use_llm: bool = True) -> Dict[str, Any]:
        """
        解析用户自然语言输入，转换为标准化操作

        Args:
            text: 用户输入的自然语言
            use_llm: 是否使用 LLM 增强（默认使用，不可用时自动降级）

        Returns:
            标准化的意图解析结果
        """
        parse_method = "rule_based"
        llm_result = None

        # 尝试 LLM 增强解析
        if use_llm and self.is_llm_enabled():
            try:
                llm_result = asyncio.run(self._parse_with_llm(text))
                if llm_result and not llm_result.get("fallback_mode", False):
                    parse_method = "llm_enhanced"
                    intent_class = llm_result.get("intent_class")
                    confidence = llm_result.get("confidence", 0.9)
                    params = llm_result.get("parameters", {})
                else:
                    # LLM 返回降级模式，继续使用规则引擎
                    llm_result = None
            except Exception:
                # LLM 调用失败，静默降级到规则引擎
                llm_result = None

        # 规则引擎解析（默认 fallback）
        if llm_result is None:
            intent_class, confidence = self._classify_intent_rule_based(text)
            params = self._extract_parameters_rule_based(text, intent_class)

        # 3. 风险评估
        risk_level = self._assess_risk(intent_class, params)

        # 4. 找出受影响的Campaign
        affected_campaigns = self._find_affected_campaigns(intent_class, params)

        # 5. 预估影响
        estimated_impact = self._estimate_impact(intent_class, affected_campaigns, params)

        # 6. 判断是否需要审批
        approval_required = risk_level in ["L1", "L2", "L3"]
        approval_deadline = None
        if approval_required and risk_level == "L1":
            approval_deadline = datetime.utcnow() + timedelta(minutes=10)

        return {
            "intent_class": intent_class,
            "confidence": confidence,
            "risk_level": risk_level,
            "parameters_extracted": params,
            "affected_campaigns": affected_campaigns,
            "estimated_impact": estimated_impact,
            "approval_required": approval_required,
            "approval_deadline": approval_deadline,
            "suggested_actions": self._generate_suggestions(intent_class, affected_campaigns, params),
            "parse_method": parse_method,
            "llm_available": self.is_llm_enabled(),
        }

    async def _parse_with_llm(self, text: str) -> Optional[Dict[str, Any]]:
        """使用 LLM 增强解析（内部方法）"""
        if not self._llm_router:
            return None

        prompt = f"""
你是一个智能投放平台的意图识别助手。请分析用户输入并返回结构化的意图分类结果。

支持的意图类型：
- campaign.pause: 暂停 Campaign
- campaign.resume: 恢复 Campaign
- campaign.budget_adjust: 调整预算
- campaign.bid_adjust: 调整出价
- campaign.optimize_batch: 批量优化
- creative.rotate: 素材轮换
- alert.review: 查看告警
- report.generate: 生成报告

需要提取的参数：
- country: 国家/地区代码 (US, JP, UK, DE, CA, BR 等)
- roi_threshold: ROI 阈值（浮点数）
- budget_adjust: 预算调整金额（浮点数）
- budget_direction: increase / decrease
- date_range: today / yesterday / last_7_days / last_30_days
- media_source: Meta / Google / TikTok

用户输入：{text}

请返回 JSON 格式：
{{
    "intent_class": "意图类型",
    "confidence": 0.0-1.0,
    "parameters": {{...}}
}}
"""

        messages = [{"role": "user", "content": prompt}]

        # 使用路由引擎选择合适的模型
        result = await self._llm_router.chat_completion(
            intent_type="campaign.optimize_batch",
            messages=messages,
            data_sensitivity="low",
        )

        if result.get("fallback_mode"):
            return {"fallback_mode": True}

        # 解析 LLM 返回的 JSON
        try:
            content = result.get("content", "")
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(content[json_start:json_end])
                parsed["routed_provider"] = result.get("routed_provider")
                return parsed
        except Exception:
            pass

        return {"fallback_mode": True}

    def _classify_intent_rule_based(self, text: str) -> Tuple[str, float]:
        """规则引擎的意图分类（始终可用，无需 LLM）"""
        text_lower = text.lower()

        matches = []
        for intent, keywords in INTENT_CLASSIFICATION.items():
            match_count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if match_count > 0:
                matches.append((intent, match_count / len(keywords)))

        if not matches:
            return "campaign.optimize_batch", 0.5

        matches.sort(key=lambda x: -x[1])
        return matches[0][0], min(matches[0][1], 1.0)

    def _extract_parameters_rule_based(self, text: str, intent_class: str) -> Dict[str, Any]:
        """规则引擎的参数提取（始终可用，无需 LLM）"""
        return self._extract_parameters(text, intent_class)

    def _extract_parameters(self, text: str, intent_class: str) -> Dict[str, Any]:
        """从文本中提取操作参数"""
        params = {}

        # 国家/地区提取
        country_match = re.search(r'(美国|US|JP|日本|英国|UK|DE|德国|CA|加拿大|BR|巴西)', text, re.IGNORECASE)
        if country_match:
            country_map = {"美国": "US", "日本": "JP", "英国": "UK", "德国": "DE", "德国": "DE"}
            country = country_match.group(1)
            params["country"] = country_map.get(country, country)

        # ROI阈值提取
        roi_match = re.search(r'ROI[低|小|于|<]\s*([0-9.]+)', text, re.IGNORECASE)
        if not roi_match:
            roi_match = re.search(r'([0-9.]+)\s*以下的ROI', text)
        if not roi_match:
            roi_match = re.search(r'roi\s*[<\s]+\s*([0-9.]+)', text, re.IGNORECASE)
        if roi_match:
            params["roi_threshold"] = float(roi_match.group(1))

        # 预算调整幅度
        budget_match = re.search(r'预算[增减]?\s*([0-9]+)', text)
        if budget_match:
            params["budget_adjust"] = float(budget_match.group(1))
            params["budget_direction"] = "increase" if "增" in text or "加" in text else "decrease"

        # 日期范围
        if "昨天" in text or "yesterday" in text.lower():
            params["date_range"] = "yesterday"
        elif "今天" in text or "today" in text.lower():
            params["date_range"] = "today"
        elif "本周" in text or "week" in text.lower():
            params["date_range"] = "this_week"
        elif "近7天" in text:
            params["date_range"] = "last_7_days"
        else:
            params["date_range"] = "last_3_days"

        # 媒体平台
        if "Meta" in text or "meta" in text or "脸书" in text:
            params["media_source"] = "Meta"
        elif "Google" in text or "google" in text:
            params["media_source"] = "Google"
        elif "TikTok" in text or "tiktok" in text:
            params["media_source"] = "TikTok"

        return params

    def _assess_risk(self, intent_class: str, params: Dict[str, Any]) -> str:
        """评估操作风险等级"""
        base_risk = RISK_LEVEL_MAP.get(intent_class, "L2")

        # 预算调整幅度过大，升级风险
        if intent_class == "campaign.budget_adjust":
            budget_change = params.get("budget_adjust", 0)
            if budget_change > 1000:  # 单日调整超过1000美金
                return "L2"

        # 涉及Campaign数量过多，升级风险
        # affected_count = params.get("affected_count", 0)
        # if affected_count > 10:
        #     return "L2"

        return base_risk

    def _find_affected_campaigns(self, intent_class: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """找出受影响的Campaign"""
        query = self.db.query(
            AggUADaily.campaign_id,
            AggUADaily.campaign_name,
            func.avg(AggUADaily.roi_7).label("avg_roi"),
            func.sum(AggUADaily.total_cost_usd).label("total_spend"),
            func.avg(AggUADaily.af_cpi).label("avg_cpi")
        ).filter(
            AggUADaily.app_id == self.app_id,
            AggUADaily.active_date >= (datetime.now() - timedelta(days=7)).date()
        )

        # 应用过滤条件
        if params.get("country"):
            query = query.filter(AggUADaily.country == params["country"])
        if params.get("media_source"):
            query = query.filter(AggUADaily.media_source == params["media_source"])

        query = query.group_by(AggUADaily.campaign_id, AggUADaily.campaign_name)

        # ROI阈值过滤
        if params.get("roi_threshold"):
            query = query.having(func.avg(AggUADaily.roi_7) < params["roi_threshold"])

        rows = query.limit(20).all()

        return [
            {
                "id": row.campaign_id,
                "name": row.campaign_name,
                "roi": float(row.avg_roi or 0),
                "spend": float(row.total_spend or 0),
                "cpi": float(row.avg_cpi or 0)
            }
            for row in rows
        ]

    def _estimate_impact(self, intent_class: str, campaigns: List[Dict], params: Dict) -> Dict[str, Any]:
        """预估操作影响"""
        total_spend = sum(c["spend"] for c in campaigns)

        if intent_class == "campaign.pause":
            return {
                "daily_spend_reduction": total_spend,
                "expected_roi_improvement": None,
                "affected_campaign_count": len(campaigns)
            }
        elif intent_class == "campaign.optimize_batch":
            # 假设将低ROI的预算转移到高ROI，整体ROI提升10%
            return {
                "daily_spend_reduction": total_spend * 0.3,  # 砍掉30%低ROI花费
                "expected_roi_improvement": 0.1,  # 预期整体ROI提升10%
                "affected_campaign_count": len(campaigns)
            }

        return {
            "daily_spend_reduction": None,
            "expected_roi_improvement": None,
            "affected_campaign_count": len(campaigns)
        }

    def _generate_suggestions(self, intent_class: str, campaigns: List[Dict], params: Dict) -> List[Dict]:
        """生成具体的操作建议列表"""
        suggestions = []

        if intent_class == "campaign.optimize_batch" or intent_class == "campaign.pause":
            for camp in campaigns:
                suggestions.append({
                    "action": "pause_campaign",
                    "campaign_id": camp["id"],
                    "campaign_name": camp["name"],
                    "reason": f"ROI={camp['roi']:.2f} 低于阈值",
                    "estimated_saving": camp["spend"]
                })

        elif intent_class == "campaign.budget_adjust":
            direction = params.get("budget_direction", "increase")
            for camp in campaigns:
                suggestions.append({
                    "action": "adjust_budget",
                    "campaign_id": camp["id"],
                    "campaign_name": camp["name"],
                    "direction": direction,
                    "amount": params.get("budget_adjust", 0),
                    "reason": "预算优化调整"
                })

        return suggestions

    def create_execution(self, parse_result: Dict[str, Any], intent_text: str) -> IntentExecution:
        """创建意图执行记录"""
        execution = IntentExecution(
            app_id=self.app_id,
            user_id=self.user.id,
            intent_text=intent_text,
            intent_class=parse_result["intent_class"],
            confidence=parse_result["confidence"],
            risk_level=parse_result["risk_level"],
            parameters_json=parse_result["parameters_extracted"],
            affected_count=len(parse_result["affected_campaigns"]),
            affected_campaigns_json=parse_result["affected_campaigns"],
            estimated_impact_json=parse_result["estimated_impact"],
            approval_required=parse_result["approval_required"],
            approval_deadline=parse_result["approval_deadline"],
            auto_execute_on_timeout=(parse_result["risk_level"] == "L0"),
            approval_status=("approved" if parse_result["risk_level"] == "L0" else "pending"),
            execution_status=("scheduled" if parse_result["risk_level"] == "L0" else "pending_approval")
        )

        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)

        # L0级别立即执行
        if parse_result["risk_level"] == "L0":
            self.execute(execution)

        return execution

    def execute(self, execution: IntentExecution) -> bool:
        """执行意图"""
        execution.execution_status = "running"
        execution.executed_at = datetime.utcnow()
        self.db.commit()

        try:
            # TODO: 实际调用媒体平台API
            # 这里先记录操作日志
            actions_log = []
            params = execution.parameters_json or {}
            campaigns = execution.affected_campaigns_json or []

            for camp in campaigns:
                action = ActionLog(
                    app_id=self.app_id,
                    user_id=self.user.id,
                    intent_execution_id=execution.id,
                    action_type=execution.intent_class,
                    campaign_id=camp["id"],
                    reason=f"Intent execution: {execution.intent_text}",
                    platform=params.get("media_source", "unknown"),
                    status="success",
                    platform_response_json={"simulated": True}
                )
                self.db.add(action)
                actions_log.append({
                    "campaign_id": camp["id"],
                    "status": "success",
                    "action": execution.intent_class
                })

            execution.actions_log_json = actions_log
            execution.execution_status = "success"
            self.db.commit()

            return True

        except Exception as e:
            execution.execution_status = "failed"
            execution.execution_error = str(e)
            self.db.commit()
            return False

    def approve(self, execution_id: int, approved: bool, reason: Optional[str] = None) -> IntentExecution:
        """审批意图执行"""
        execution = self.db.query(IntentExecution).filter(
            IntentExecution.id == execution_id,
            IntentExecution.app_id == self.app_id
        ).first()

        if not execution:
            raise ValueError("Execution not found")

        execution.approved_by = self.user.id
        execution.approved_at = datetime.utcnow()

        if approved:
            execution.approval_status = "approved"
            # 立即执行
            self.execute(execution)
        else:
            execution.approval_status = "rejected"
            execution.execution_status = "rejected"
            execution.rejection_reason = reason

        self.db.commit()
        return execution


def get_intent_engine(db: Session, user: User, app_id: int) -> IntentEngine:
    """获取意图引擎实例"""
    return IntentEngine(db, user, app_id)
