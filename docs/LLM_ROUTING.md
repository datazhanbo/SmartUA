# SmartUA - 大模型路由系统

## 核心设计原则

### 1. 服务启动与大模型集成解耦
✅ **关键特性**：
- 服务无需任何 LLM API Key 即可正常启动和运行
- 所有核心功能（数据查询、意图识别、操作执行）都不依赖 LLM
- LLM 是增强层，不是依赖层

### 2. 优雅降级机制
```
用户输入
    ↓
┌─ 尝试 LLM 增强解析 ─┐
│  ✓ 成功 → 返回增强结果
│  ✗ 失败（无API/超时/错误）
└─────── ↓ ───────────┘
    规则引擎解析（始终可用）
    ↓
返回结果
```

### 3. 多模型智能路由
根据**意图复杂度**、**数据敏感性**、**响应时间要求**、**成本预算**自动选择最优模型。

---

## 支持的 LLM Providers

| Provider | 模型 | 能力标签 | 成本($/1k tokens) | 平均延迟 | 优先级 |
|----------|------|---------|-----------------|---------|-------|
| **Claude** | Claude 3.5 Sonnet | 复杂分析、策略生成、创意 | 3.0 | 2000ms | 1 |
| **GPT-4o** | GPT-4o | 快速响应、创意生成 | 2.5 | 1500ms | 2 |
| **DeepSeek** | DeepSeek V3 | 代码生成、快速响应 | 1.0 | 800ms | 3 |
| **本地模型** | Qwen 2.5 72B | 敏感数据、内部分析 | 0.1 | 5000ms | 4 |

---

## 路由策略

### 1. 按意图类型路由
| 意图类型 | 首选 Provider | 能力要求 |
|---------|--------------|---------|
| `campaign.optimize_batch` | Claude | 复杂意图 + 策略分析 |
| `creative.rotate` | GPT-4o | 创意生成 |
| `campaign.pause/resume` | DeepSeek | 快速响应 |
| 涉及敏感数据 | 本地模型 | 数据不出域 |

### 2. 可配置全局策略
在 `settings.py` 中配置：
```python
llm_routing_strategy = "best_fit"  # 综合最优
# llm_routing_strategy = "fastest"   # 响应最快
# llm_routing_strategy = "least_cost" # 成本最低
# llm_routing_strategy = "highest_quality" # 质量最优
```

### 3. Fallback 链
```
首选模型失败 → 尝试备用模型 → 都失败？自动降级到规则引擎
```

---

## API 接口

### GET `/api/v1/llm/status`
查看 LLM 路由系统状态和各 Provider 可用性

**响应示例**：
```json
{
    "llm_available": true,
    "routing_strategy": "best_fit",
    "fallback_enabled": true,
    "providers": {
        "claude": { "available": false, "name": "Claude 3.5 Sonnet", ... },
        "gpt4": { "available": false, "name": "GPT-4o", ... },
        "deepseek": { "available": false, "name": "DeepSeek V3", ... },
        "local": { "available": true, "name": "Qwen 2.5 72B", ... }
    }
}
```

### POST `/api/v1/llm/test-route?intent_type=xxx&data_sensitivity=low`
测试路由决策结果

---

## 配置方式

### 环境变量配置
在 `.env` 文件中配置：
```env
# Claude
CLAUDE_API_KEY=sk-ant-xxx

# OpenAI
OPENAI_API_KEY=sk-xxx

# DeepSeek
DEEPSEEK_API_KEY=sk-xxx

# 本地模型
LOCAL_MODEL_BASE_URL=http://localhost:8000/v1
LOCAL_MODEL_NAME=qwen2.5-72b-instruct

# 路由策略
LLM_ROUTING_STRATEGY=best_fit
```

### 无需配置即可运行
不配置任何 API Key 时，系统自动进入**纯规则引擎模式**，所有功能正常可用。

---

## 解析模式说明

| 模式 | 触发条件 | 特点 |
|-----|---------|------|
| **llm_enhanced** | 至少一个 Provider 可用 + 解析成功 | 更高准确率、更智能的参数提取 |
| **rule_based** | 无可用 LLM 或 LLM 调用失败 | 稳定可靠、零延迟、始终可用 |

在意图解析结果中可查看当前模式：
```json
{
    "parse_method": "rule_based",
    "llm_available": false
}
```

---

## 能力扩展

### 添加新的 LLM Provider
1. 在 `app/services/llm/router.py` 中继承 `LLMProvider` 基类
2. 实现 `chat_completion()` 和 `is_available()` 方法
3. 在 `settings.py` 的 `get_llm_providers_config()` 中注册

### 自定义路由规则
在 `LLMRouter.route()` 方法中添加自定义逻辑，或扩展 `routing_rules` 配置。

---

## 测试验证

### 验证解耦特性
```bash
# 1. 不配置任何 API Key 启动服务
# 2. 所有 API 正常响应
# 3. 意图解析使用 rule_based 模式

# 查看 LLM 状态
curl http://localhost:8000/api/v1/llm/status

# 测试意图解析（纯规则引擎）
curl -X POST http://localhost:8000/api/v1/intent/parse \
  -d '{"text":"暂停 ROI 低于 0.5 的 Campaign","app_id":1}'
```

### 验证 LLM 增强
```bash
# 1. 配置 CLAUDE_API_KEY 环境变量
# 2. 重启服务
# 3. 意图解析自动切换到 llm_enhanced 模式

export CLAUDE_API_KEY=sk-ant-xxx
# 重启服务后...
```

---

## 架构优势

1. **无强制依赖**：LLM 是可选增强，不是系统运行的必要条件
2. **渐进式启用**：可以先上线基础功能，后续再配置 LLM 增强体验
3. **高可用性**：LLM 服务中断不影响核心投放操作
4. **成本可控**：按意图类型路由到成本最合适的模型
5. **隐私保护**：敏感数据自动走本地模型，数据不出域
