from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional, Any
import hashlib
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 币种换算（spend_usd 接地）：静态回退表，DB 无汇率时使用，避免非 USD 账户错算。
# 值 = 1 单位 quote_currency 折合多少 USD（近似，随市场浮动，仅作默认基线）。
# ---------------------------------------------------------------------------
_FX_STATIC = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067, "CAD": 0.73,
    "AUD": 0.66, "CNY": 0.14, "KRW": 0.00073, "INR": 0.012, "BRL": 0.18,
    "MXN": 0.058, "IDR": 0.000063, "THB": 0.028, "VND": 0.000040, "TWD": 0.031,
    "HKD": 0.128, "SGD": 0.74, "SEK": 0.095, "CHF": 1.12, "PLN": 0.25,
    "ZAR": 0.053, "TRY": 0.030, "AED": 0.27, "SAR": 0.27, "NOK": 0.092,
    "DKK": 0.145, "CZK": 0.043, "HUF": 0.0027, "RON": 0.22, "ILS": 0.27,
    "PHP": 0.017, "MYR": 0.21, "NZD": 0.60, "EGP": 0.020, "NGN": 0.00065,
}


def to_usd(amount, currency: str, db=None, app_id=None) -> float:
    """把某币种金额换算为 USD。DB 有最新汇率优先；否则静态表；再否则 1.0 并告警。"""
    if currency in (None, "", "USD"):
        return float(amount or 0)
    cur = str(currency).upper()
    rate = None
    if db is not None:
        from app.models.data import DimFxRate
        try:
            row = db.query(DimFxRate).filter(
                DimFxRate.quote_currency == cur
            ).order_by(DimFxRate.as_of_date.desc()).first()
            if row and row.rate is not None:
                rate = float(row.rate)
        except Exception:
            pass
    if rate is None:
        rate = _FX_STATIC.get(cur)
    if rate is None:
        logger.warning(f"无 {cur} 汇率（DB/静态均无），按 1.0 处理 spend_usd")
        rate = 1.0
    return float(amount or 0) * rate


@dataclass
class ImpactEstimation:
    """动作影响的估计载体（与 MockMediaConnector 引擎返回结构兼容：delta_roi/delta_spend/delta_cpi 均为等长 float 列表）。

    真实连接器无因果引擎时返回全 0，上层 loop 据此给出"中性预测"而非崩溃。
    """

    delta_roi: List[float]
    delta_spend: List[float]
    delta_cpi: List[float]


class BaseConnector(ABC):
    """所有连接器的基类"""

    platform: str           # 平台标识，如 "meta", "google"
    source_type: str        # "media" / "mmp" / "dsp"
    rate_limit: int = 60    # API 每秒请求限制
    timeout: int = 30       # 请求超时时间（秒）

    # Phase 1.1：显式声明该连接器支持的执行模式与能力，禁止 live 与 mock 静默互切。
    supported_modes: tuple = ("mock",)
    capabilities: Dict[str, bool] = {
        "read": True,
        "write": False,
        "structure": False,
        "simulate": False,
    }

    def __init__(
        self,
        db: Session,
        app_id: int,
        credentials: Dict[str, Any],
        execution_mode: str = "mock",
    ):
        if execution_mode not in self.supported_modes:
            raise ValueError(
                f"{self.__class__.__name__} 不支持执行模式 '{execution_mode}'；"
                f"支持: {list(self.supported_modes)}"
            )
        self.db = db
        self.app_id = app_id
        self.credentials = credentials
        self.execution_mode: str = execution_mode
        # 连接器自身用于身份声明的账户 ID（真实连接器初始化时应赋值，Mock 保持空串）
        self.account_id: str = ""
        self.client = None
        self.run_id: Optional[int] = None

    # ---------------- 结果 provenance（Phase 1.1） ----------------
    def _result_meta(self) -> Dict[str, Any]:
        """所有 pull/action 返回都应带上：平台、执行模式、账户与验证时间。"""
        return {
            "platform": self.platform,
            "execution_mode": self.execution_mode,
            "account_id": self.account_id,
            "is_mock": self.execution_mode != "live",
            "verified_at": datetime.utcnow().isoformat() + "Z",
        }

    def _decorate_pull_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        meta = result.get("metadata") if isinstance(result, dict) else None
        if not isinstance(meta, dict):
            meta = {}
        meta.update(self._result_meta())
        result["metadata"] = meta
        return result

    def _decorate_action_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return result
        for k, v in self._result_meta().items():
            result.setdefault(k, v)
        return result

    @abstractmethod
    def auth(self) -> bool:
        """认证方法"""
        pass

    @abstractmethod
    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str = "campaign_daily",
             **kwargs) -> Dict[str, Any]:
        """拉取数据核心方法"""
        pass

    @abstractmethod
    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """字段标准化转换"""
        pass

    def validate(self, rows: List[Dict]) -> bool:
        """数据校验（可选重写）"""
        if not rows:
            return True

        required_fields = ["date", "campaign_id", "impressions", "clicks", "spend"]
        for row in rows:
            for field in required_fields:
                if field not in row or row[field] is None:
                    logger.warning(f"Missing required field: {field} in row")
                    return False

            if row.get("impressions", 0) < 0:
                logger.warning("Invalid negative impressions")
                return False
            if row.get("clicks", 0) < 0:
                logger.warning("Invalid negative clicks")
                return False
            if row.get("spend", 0) < 0:
                logger.warning("Invalid negative spend")
                return False

        return True

    def _calculate_row_hash(self, row: Dict) -> str:
        """计算行数据唯一哈希，用于幂等性保证"""
        hash_components = [
            self.platform,
            str(row.get("date", "")),
            str(row.get("campaign_id", "")),
            str(row.get("adset_id", "")),
            str(row.get("ad_id", "")),
            str(row.get("country", "ALL")),
            str(row.get("account_id", "")),
        ]
        hash_string = "|".join(hash_components)
        return hashlib.md5(hash_string.encode("utf-8")).hexdigest()

    def save_ods(self, raw_data: Dict, run_id: int) -> int:
        """保存原始数据到 ODS 层（统一实现）"""
        from app.models.data import RawPayload
        import json

        raw_rows = raw_data.get("raw_rows", [])
        metadata = raw_data.get("metadata", {})

        if not raw_rows:
            return 0

        # 确保日期字段是字符串格式
        def ensure_date_str(d):
            if isinstance(d, date):
                return d.isoformat()
            return str(d) if d else None

        safe_metadata = dict(metadata)
        safe_metadata["date_from"] = ensure_date_str(metadata.get("date_from"))
        safe_metadata["date_to"] = ensure_date_str(metadata.get("date_to"))

        payload_json = {
            "platform": self.platform,
            "source_type": self.source_type,
            "pulled_at": datetime.utcnow().isoformat(),
            "rows": raw_rows,
            "metadata": safe_metadata
        }

        payload_str = json.dumps(payload_json, sort_keys=True)
        payload_hash = hashlib.md5(payload_str.encode("utf-8")).hexdigest()

        # 转换回 date 对象用于数据库
        def parse_date(d):
            if isinstance(d, date):
                return d
            if d:
                from datetime import datetime as dt
                return dt.strptime(str(d).split("T")[0], "%Y-%m-%d").date()
            return None

        raw_payload = RawPayload(
            run_id=run_id,
            app_id=self.app_id,
            connector=self.platform,
            source_type=self.source_type,
            report_type=safe_metadata.get("report_type", "campaign_daily"),
            endpoint=safe_metadata.get("endpoint", ""),
            account_id=safe_metadata.get("account_id", ""),
            app_key=safe_metadata.get("app_key", ""),
            date_from=parse_date(safe_metadata.get("date_from")),
            date_to=parse_date(safe_metadata.get("date_to")),
            request_hash=safe_metadata.get("request_hash", ""),
            payload_hash=payload_hash,
            row_count=len(raw_rows),
            payload_json=payload_json,
            file_size_bytes=len(payload_str.encode("utf-8"))
        )

        self.db.add(raw_payload)
        self.db.flush()

        return len(raw_rows)

    def save_dwd(self, normalized_rows: List[Dict], run_id: int) -> int:
        """保存标准化数据到 DWD 层（统一实现）"""
        from app.models.data import FactMediaDaily, FactMMPDaily
        from sqlalchemy.dialects.postgresql import insert

        if not normalized_rows:
            return 0

        saved_count = 0

        if self.source_type == "media":
            for row in normalized_rows:
                source_row_hash = self._calculate_row_hash(row)

                # 转换 date
                row_date = row.get("date")
                if isinstance(row_date, str):
                    from datetime import datetime as dt
                    row_date = dt.strptime(row_date.split("T")[0], "%Y-%m-%d").date()

                insert_stmt = insert(FactMediaDaily).values(
                    run_id=run_id,
                    app_id=self.app_id,
                    source_platform=self.platform,
                    source_type=self.source_type,
                    date=row_date,
                    account_id=row.get("account_id", ""),
                    app_key=row.get("app_key", ""),
                    media_source=row.get("media_source", self.platform),
                    campaign_id=str(row.get("campaign_id", "")),
                    campaign_name=row.get("campaign_name", ""),
                    adset_id=str(row.get("adset_id", "")),
                    adset_name=row.get("adset_name", ""),
                    ad_id=str(row.get("ad_id", "")),
                    ad_name=row.get("ad_name", ""),
                    creative_id=str(row.get("creative_id", "")),
                    creative_name=row.get("creative_name", ""),
                    country=row.get("country", "ALL"),
                    currency=row.get("currency", "USD"),
                    impressions=row.get("impressions", 0),
                    clicks=row.get("clicks", 0),
                    spend=row.get("spend", 0),
                    spend_usd=row.get("spend_usd", row.get("spend", 0)),
                    media_installs=row.get("installs", 0),
                    media_conversions=row.get("conversions", 0),
                    ctr=row.get("ctr", 0),
                    cpc=row.get("cpc", 0),
                    cpm=row.get("cpm", 0),
                    cpi=row.get("cpi", 0),
                    source_row_hash=source_row_hash,
                    raw_row_json=row
                )

                do_nothing_stmt = insert_stmt.on_conflict_do_nothing(
                    index_elements=["source_row_hash"]
                )
                self.db.execute(do_nothing_stmt)
                saved_count += 1

        elif self.source_type == "mmp":
            for row in normalized_rows:
                source_row_hash = self._calculate_row_hash(row)

                # 转换 date
                row_date = row.get("date")
                if isinstance(row_date, str):
                    from datetime import datetime as dt
                    row_date = dt.strptime(row_date.split("T")[0], "%Y-%m-%d").date()

                insert_stmt = insert(FactMMPDaily).values(
                    run_id=run_id,
                    app_id=self.app_id,
                    mmp=self.platform,
                    date=row_date,
                    app_key=row.get("app_key", ""),
                    platform=row.get("platform", ""),
                    media_source=row.get("media_source", ""),
                    campaign_id=str(row.get("campaign_id", "")),
                    campaign_name=row.get("campaign_name", ""),
                    adset_id=str(row.get("adset_id", "")),
                    adset_name=row.get("adset_name", ""),
                    ad_id=str(row.get("ad_id", "")),
                    ad_name=row.get("ad_name", ""),
                    country=row.get("country", "ALL"),
                    attribution_model=row.get("attribution_model", "aggregate"),
                    signal_confidence=row.get("signal_confidence", "medium"),
                    currency=row.get("currency", "USD"),
                    attributed_installs=row.get("attributed_installs", 0),
                    registrations=row.get("registrations", 0),
                    payers=row.get("payers", 0),
                    cost=row.get("cost", 0),
                    cost_usd=row.get("cost_usd", row.get("cost", 0)),
                    revenue=row.get("revenue", 0),
                    revenue_usd=row.get("revenue_usd", row.get("revenue", 0)),
                    roi_d0=row.get("roi_d0", 0),
                    roi_d1=row.get("roi_d1", 0),
                    roi_d3=row.get("roi_d3", 0),
                    roi_d7=row.get("roi_d7", 0),
                    roi_d14=row.get("roi_d14", 0),
                    roi_d30=row.get("roi_d30", 0),
                    retention_d1=row.get("retention_d1", 0),
                    retention_d3=row.get("retention_d3", 0),
                    retention_d7=row.get("retention_d7", 0),
                    retention_d14=row.get("retention_d14", 0),
                    retention_d30=row.get("retention_d30", 0),
                    source_row_hash=source_row_hash,
                    raw_row_json=row
                )

                do_nothing_stmt = insert_stmt.on_conflict_do_nothing(
                    index_elements=["source_row_hash"]
                )
                self.db.execute(do_nothing_stmt)
                saved_count += 1

        self.db.flush()
        return saved_count

    def create_run_record(self,
                          operation: str,
                          report_type: str,
                          date_from: date,
                          date_to: date,
                          account_id: str = "",
                          app_key: str = "",
                          params_json: Dict = None,
                          executed_by: int = None) -> int:
        """创建连接器运行记录"""
        from app.models.data import ConnectorRun

        run = ConnectorRun(
            app_id=self.app_id,
            connector=self.platform,
            source_type=self.source_type,
            operation=operation,
            report_type=report_type,
            date_from=date_from,
            date_to=date_to,
            account_id=account_id,
            app_key=app_key,
            params_json=params_json or {},
            status="running",
            raw_row_count=0,
            normalized_row_count=0,
            executed_by=executed_by
        )

        self.db.add(run)
        self.db.flush()
        self.run_id = run.id
        return run.id

    def update_run_success(self, raw_row_count: int, normalized_row_count: int, adapter_response_json: Dict = None):
        """更新运行记录为成功状态"""
        if not self.run_id:
            return

        from app.models.data import ConnectorRun
        import json

        # 确保日期被正确序列化
        def date_serializer(obj):
            if isinstance(obj, date):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        safe_response = {}
        if adapter_response_json:
            # 使用自定义序列化器确保日期都被转换
            json_str = json.dumps(adapter_response_json, default=date_serializer)
            safe_response = json.loads(json_str)

        run = self.db.query(ConnectorRun).filter(ConnectorRun.id == self.run_id).first()
        if run:
            run.status = "success"
            run.raw_row_count = raw_row_count
            run.normalized_row_count = normalized_row_count
            run.adapter_response_json = safe_response
            self.db.commit()

    def update_run_failed(self, error_detail: str):
        """更新运行记录为失败状态"""
        if not self.run_id:
            return

        from app.models.data import ConnectorRun

        run = self.db.query(ConnectorRun).filter(ConnectorRun.id == self.run_id).first()
        if run:
            run.status = "failed"
            run.error_detail = error_detail
            self.db.commit()

    def execute_pull(self,
                     date_from: date,
                     date_to: date,
                     report_type: str = "campaign_daily",
                     account_id: str = "",
                     app_key: str = "",
                     executed_by: int = None,
                     **kwargs) -> Dict[str, Any]:
        """完整的拉取执行流程"""
        try:
            run_id = self.create_run_record(
                operation="pull",
                report_type=report_type,
                date_from=date_from,
                date_to=date_to,
                account_id=account_id,
                app_key=app_key,
                executed_by=executed_by,
                params_json=kwargs
            )

            if not self.auth():
                self.update_run_failed("Authentication failed")
                return {"success": False, "error": "Authentication failed"}

            raw_data = self.pull(date_from, date_to, report_type, **kwargs)
            raw_data = self._decorate_pull_result(raw_data)
            raw_rows = raw_data.get("raw_rows", [])
            metadata = raw_data.get("metadata", {})

            if not raw_rows:
                self.update_run_success(0, 0, metadata)
                return {"success": True, "raw_rows": 0, "normalized_rows": 0}

            normalized_rows = self.normalize(raw_rows)

            if not self.validate(normalized_rows):
                logger.warning("Data validation failed, proceeding with caution")

            self.save_ods(raw_data, run_id)
            normalized_count = self.save_dwd(normalized_rows, run_id)

            self.db.commit()
            self.update_run_success(len(raw_rows), normalized_count, metadata)

            return {
                "success": True,
                "raw_rows": len(raw_rows),
                "normalized_rows": normalized_count,
                "run_id": run_id
            }

        except Exception as e:
            self.db.rollback()
            error_msg = f"Connector execution failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.update_run_failed(error_msg)
            return {"success": False, "error": error_msg}

    def apply_action(self, action: str, entity_id: str, **params) -> Dict[str, Any]:
        """通用写动作分发器：把 Agent Tool Registry 的动作映射到具体连接器方法。

        设计目的（见 docs/AGENTIC_AD_PLATFORM_UPGRADE.md）：
        Agent Loop 的写工具统一调用此方法，而非具体连接器方法，从而与连接器解耦——
        Meta 账户恢复后只需在工厂把 "mock" 换回 "meta"，上层 Tool Registry 与
        意图引擎零改动。子类可重写以实现自定义语义；默认实现映射到标准 update_* 方法。

        支持的动作：
        - update_campaign_status / update_campaign_budget
        - update_adset_status / update_adset_bid
        - rotate_creative（仅当连接器实现了该方法，如 MockMediaConnector）

        写成功后自动回写 dim_campaign_structure，使 current_summary() 能反映最新
        运营态（status / 预算），无需等待下一次 pull_structure。
        """
        if action == "update_campaign_status":
            result = self.update_campaign_status(entity_id, params.get("status", "ACTIVE"))
        elif action == "update_campaign_budget":
            result = self.update_campaign_budget(entity_id, float(params.get("daily_budget", 0)))
        elif action == "update_adset_bid":
            result = self.update_adset_bid(entity_id, float(params.get("bid_amount", 1.0)))
        elif action == "update_adset_status":
            fn = getattr(self, "update_adset_status", None)
            if fn is None:
                return {"success": False, "error": f"{self.platform} 连接器不支持 update_adset_status"}
            result = fn(entity_id, params.get("status", "ACTIVE"))
        elif action == "rotate_creative":
            fn = getattr(self, "rotate_creative", None)
            if fn is None:
                return {"success": False, "error": f"{self.platform} 连接器不支持 rotate_creative"}
            result = fn(entity_id)
        else:
            return {"success": False, "error": f"不支持的动作: {action}"}

        if result.get("success"):
            try:
                self._record_structure_change(action, entity_id, params)
            except Exception as e:
                logger.warning(f"写动作回写结构表失败（不影响主流程）: {e}")
        return self._decorate_action_result(result)

    # ---------------- 计划分层结构（DIM）拉取与存储 ----------------
    def pull_structure(self) -> Dict[str, Any]:
        """拉取 Campaign->AdSet->Ad->Creative 层级与运营态。基类默认返回空（如 MMP/无结构概念的连接器）。"""
        return {"raw_rows": [], "metadata": {"mode": "na", "platform": self.platform}}

    def _upsert_structure(self, **vals) -> None:
        """DB 无关地 upsert 一条结构维度行（按 app_id+platform+entity_level+entity_id）。"""
        from app.models.data import DimCampaignStructure
        from datetime import date as _date
        today = _date.today()
        existing = self.db.query(DimCampaignStructure).filter_by(
            app_id=self.app_id,
            source_platform=self.platform,
            entity_level=vals["entity_level"],
            entity_id=vals["entity_id"],
        ).first()
        if existing:
            for k, v in vals.items():
                if k in ("app_id", "source_platform", "entity_level", "entity_id", "first_seen_date"):
                    continue
                setattr(existing, k, v)
            existing.version = (existing.version or 0) + 1
            existing.as_of_date = today
        else:
            vals = dict(vals)
            vals["first_seen_date"] = today
            vals["as_of_date"] = today
            vals["version"] = 1
            self.db.add(DimCampaignStructure(**vals))
        self.db.flush()

    def save_structure(self, raw_rows: List[Dict], run_id: int) -> int:
        """把 pull_structure 的 raw_rows upsert 进 dim_campaign_structure。"""
        if not raw_rows or self.db is None:
            return 0
        for r in raw_rows:
            self._upsert_structure(
                app_id=self.app_id,
                source_platform=self.platform,
                account_id=r.get("account_id", ""),
                entity_level=r["entity_level"],
                entity_id=str(r["entity_id"]),
                parent_id=r.get("parent_id"),
                campaign_id=r.get("campaign_id"),
                campaign_name=r.get("campaign_name"),
                adset_id=r.get("adset_id"),
                adset_name=r.get("adset_name"),
                ad_id=r.get("ad_id"),
                ad_name=r.get("ad_name"),
                creative_id=r.get("creative_id"),
                creative_name=r.get("creative_name"),
                status=r.get("status"),
                daily_budget=r.get("daily_budget"),
                bid_amount=r.get("bid_amount"),
                currency=r.get("currency", "USD"),
                targeting_json=r.get("targeting_json"),
            )
        return len(raw_rows)

    def _record_structure_change(self, action: str, entity_id: str, params: Dict) -> None:
        """写动作成功后回写结构表：仅更新已知字段，不抹掉其它层级信息。"""
        if self.db is None:
            return
        level = "campaign"
        fields = {}
        if action == "update_campaign_status":
            level = "campaign"
            fields["status"] = str(params.get("status", "ACTIVE")).upper()
        elif action == "update_campaign_budget":
            level = "campaign"
            fields["daily_budget"] = float(params.get("daily_budget", 0))
        elif action == "update_adset_bid":
            level = "adset"
            fields["bid_amount"] = float(params.get("bid_amount", 0))
        elif action == "update_adset_status":
            level = "adset"
            fields["status"] = str(params.get("status", "ACTIVE")).upper()
        else:
            return
        from app.models.data import DimCampaignStructure
        row = self.db.query(DimCampaignStructure).filter_by(
            app_id=self.app_id, source_platform=self.platform,
            entity_level=level, entity_id=str(entity_id),
        ).first()
        if row is None:
            self._upsert_structure(
                app_id=self.app_id, source_platform=self.platform,
                entity_level=level, entity_id=str(entity_id),
                status=fields.get("status"), daily_budget=fields.get("daily_budget"),
                bid_amount=fields.get("bid_amount"),
            )
        else:
            for k, v in fields.items():
                setattr(row, k, v)
            row.version = (row.version or 0) + 1
            row.as_of_date = __import__("datetime").date.today()

    def execute_structure_pull(self, account_id: str = "", executed_by: int = None) -> Dict[str, Any]:
        """结构拉取完整流程（与 execute_pull 对称）。"""
        try:
            run_id = self.create_run_record(
                operation="pull_structure", report_type="structure",
                date_from=__import__("datetime").date.today(),
                date_to=__import__("datetime").date.today(),
                account_id=account_id, executed_by=executed_by,
            )
            if not self.auth():
                self.update_run_failed("Authentication failed")
                return {"success": False, "error": "Authentication failed"}

            raw_data = self.pull_structure()
            raw_rows = raw_data.get("raw_rows", [])
            if not raw_rows:
                self.update_run_success(0, 0, raw_data.get("metadata", {}))
                return {"success": True, "rows": 0, "run_id": run_id}

            saved = self.save_structure(raw_rows, run_id)
            self.db.commit()
            self.update_run_success(len(raw_rows), saved, raw_data.get("metadata", {}))
            return {"success": True, "rows": saved, "run_id": run_id}
        except Exception as e:
            self.db.rollback()
            error_msg = f"结构拉取失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.update_run_failed(error_msg)
            return {"success": False, "error": error_msg}

    # ---------------- Agent 辅助接口（媒体连接器通用实现） ----------------
    # MockMediaConnector 用有状态 SimulationEngine 覆盖这三者；其余真实连接器
    # 默认走"基于 FactMediaDaily 的真实聚合"，从而在没有因果引擎时也能接地真实数据。
    def account_status(self) -> str:
        """媒体账户状态；默认 ok。子类（如 MockMediaConnector）可覆盖以反映封户/受限。"""
        return "ok"

    def read_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Phase 3.3 —— 回读单个实体的最新状态，供 dispatcher 做 accepted → verified 对账。

        默认实现从 `current_summary()` 匹配 `campaign_id == entity_id` 的行返回
        `{status, daily_budget, roi, spend, cpi}`。真实 Connector（未来）应改为直接
        调用媒体 API 的"取实体状态"接口；找不到返回 None，dispatcher 据此把动作停在
        `unknown`（媒体也许已改动、但无法确认），等待人工/后续对账收敛。
        """
        if not entity_id:
            return None
        try:
            rows = self.current_summary()
        except Exception as e:
            logger.warning("read_state via current_summary failed: %s", e)
            return None
        for r in rows or []:
            if str(r.get("campaign_id")) == str(entity_id):
                return {
                    "status": r.get("status"),
                    "daily_budget": r.get("daily_budget"),
                    "roi": r.get("roi"),
                    "spend": r.get("spend"),
                    "cpi": r.get("cpi"),
                }
        return None

    def simulate_impact(self, action: str, entity_id: str, params: Dict, horizon: int = 7):
        """动作影响占位估计：无因果引擎时返回全 0（上层 loop 据此给出中性预测）。"""
        n = max(1, int(horizon))
        zeros = [0.0] * n
        return ImpactEstimation(delta_roi=list(zeros), delta_spend=list(zeros), delta_cpi=list(zeros))

    def current_summary(self) -> List[Dict]:
        """基于 FactMediaDaily 聚合最新一天账户概览（真实数据接地）。

        返回与 MockMediaConnector.live_summary() 兼容的 dict 列表，键含：
        campaign_id / country / status / roi / spend / cpi / daily_budget / creative_age。
        - roi：若同一 app 的 MMP（FactMMPDaily）存在匹配 campaign 的 roi_d7，则取之；否则 None
          （上层检测器 / 规则引擎已对 roi is None 做了跳过处理，避免误报）。
        - status / daily_budget：优先取自 dim_campaign_structure（pull_structure 写入的真实运营态）；
          结构表无对应 campaign 时回退 None（不再硬编码 ACTIVE，避免误导暂停/预算状态）。
        - creative_age：取该 campaign 下 creative 层级 first_seen_date 距今天数（若有）。
        """
        if self.db is None:
            return []
        from app.models.data import FactMediaDaily, FactMMPDaily, DimCampaignStructure
        from sqlalchemy import func
        from datetime import date as _date

        latest = self.db.query(func.max(FactMediaDaily.date)).filter(
            FactMediaDaily.app_id == self.app_id,
            FactMediaDaily.source_platform == self.platform,
        ).scalar()
        if latest is None:
            return []

        rows = self.db.query(FactMediaDaily).filter(
            FactMediaDaily.app_id == self.app_id,
            FactMediaDaily.source_platform == self.platform,
            FactMediaDaily.date == latest,
        ).all()

        groups: Dict[tuple, Dict[str, float]] = {}
        for r in rows:
            key = (r.campaign_id, r.country)
            g = groups.setdefault(key, {"spend": 0.0, "installs": 0.0})
            g["spend"] += float(r.spend or 0)
            g["installs"] += float(r.media_installs or 0)

        # 结构表：campaign 运营态 + creative 首见日
        struct_campaign: Dict[str, DimCampaignStructure] = {}
        struct_creative_first: Dict[str, _date] = {}
        try:
            srows = self.db.query(DimCampaignStructure).filter(
                DimCampaignStructure.app_id == self.app_id,
                DimCampaignStructure.source_platform == self.platform,
            ).all()
            for s in srows:
                if s.entity_level == "campaign" and s.campaign_id:
                    struct_campaign[s.campaign_id] = s
                elif s.entity_level == "creative" and s.first_seen_date:
                    cid = s.campaign_id
                    if cid and (cid not in struct_creative_first or s.first_seen_date < struct_creative_first[cid]):
                        struct_creative_first[cid] = s.first_seen_date
        except Exception:
            pass

        # 尽量从 MMP 归因拿 roi（最佳努力；无 MMP 数据时 roi 保持 None）
        roi_map: Dict[str, float] = {}
        try:
            mmp_rows = self.db.query(FactMMPDaily).filter(
                FactMMPDaily.app_id == self.app_id,
                FactMMPDaily.date == latest,
            ).all()
            for m in mmp_rows:
                if m.campaign_id and m.roi_d7 is not None:
                    roi_map[m.campaign_id] = float(m.roi_d7)
        except Exception:
            pass

        out = []
        for (cid, country), g in groups.items():
            cpi = (g["spend"] / g["installs"]) if g["installs"] > 0 else 0.0
            roi = roi_map.get(cid)
            struct = struct_campaign.get(cid)
            daily_budget = float(struct.daily_budget) if struct and struct.daily_budget is not None else None
            status = struct.status if struct and struct.status else None
            creative_age = None
            fs = struct_creative_first.get(cid)
            if fs:
                creative_age = (_date.today() - fs).days
            out.append({
                "campaign_id": cid,
                "country": country,
                "status": status,
                "roi": roi,
                "spend": round(g["spend"], 2),
                "cpi": round(cpi, 2),
                "daily_budget": round(daily_budget, 2) if daily_budget is not None else None,
                "creative_age": creative_age,
            })
        return out
