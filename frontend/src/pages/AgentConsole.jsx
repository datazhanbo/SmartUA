import React, { useState, useEffect, useRef } from 'react'
import {
  Card, Input, Button, Tag, Space, Select, Alert, Collapse, Empty, Spin,
  message, Tooltip, Divider, Typography, Progress, Badge, Tabs, Switch
} from 'antd'
import {
  RobotOutlined, SendOutlined, PlusOutlined, ReloadOutlined,
  AimOutlined, SafetyOutlined, CheckCircleOutlined, StopOutlined,
  ThunderboltOutlined, BellOutlined, EyeOutlined, ScanOutlined, PoweroffOutlined
} from '@ant-design/icons'
import { agentAPI } from '../api'

const { TextArea } = Input
const { Title, Text, Paragraph } = Typography

// 当前对接的 app（与后端 mock 引擎 / 会话仓库同源，演示用 app_id=1）
const APP_ID = 1

// 步骤类型 → 渲染配置
const KIND_META = {
  reasoning: { emoji: '🧠', color: '#722ed1', label: '思考过程' },
  thought: { emoji: '💭', color: '#8c8c8c', label: '决策理由' },
  observation: { emoji: '👁', color: '#8c8c8c', label: '观察' },
  action: { emoji: '✅', color: '#52c41a', label: '已执行' },
  approval: { emoji: '⏳', color: '#faad14', label: '待审批' },
  final: { emoji: '🏁', color: '#1890ff', label: '结论' },
}

const SESSION_STATUS = {
  running: { color: 'blue', label: '运行中' },
  awaiting_approval: { color: 'orange', label: '待你审批' },
  done: { color: 'green', label: '已完成' },
  failed: { color: 'red', label: '失败' },
}

// 快捷目标示例
const SAMPLE_GOALS = [
  '暂停 ROI 低于 0.5 的 campaign，给 ROI 最高的加预算 20%，并轮换表现最差的素材',
  '给高 ROI 的 campaign 加预算提量',
  '分析一下当前账户表现，给出优化建议',
]

// 主动自治：异常严重度 → 颜色
const SEVERITY_COLOR = { info: 'blue', warning: 'orange', critical: 'red' }
// 主动自治：告警状态 → 标签
const ALERT_STATUS = {
  auto_executed: { color: 'green', label: '✅ 已自动处置' },
  pending_approval: { color: 'orange', label: '⏳ 待你审批' },
  no_action: { color: 'default', label: 'ℹ️ 仅通知' },
  approved: { color: 'green', label: '已批准' },
  rejected: { color: 'red', label: '已驳回' },
}

// ----------------------------- Provenance 标签 ----------------------------- //
// Phase 1.2：会话 / 步骤 / 告警在任何时候都要能告诉用户"这条动作作用在 Mock / Sandbox / Live 的哪个账户"。
const EXEC_MODE_META = {
  mock:    { color: 'default',   label: 'MOCK',    tip: '模拟数据，不影响真实账户' },
  sandbox: { color: 'geekblue',  label: 'SANDBOX', tip: '沙箱环境，不影响真实预算' },
  live:    { color: 'red',       label: 'LIVE',    tip: '真实账户，动作将扣真实预算' },
}

function ProvenanceTag({ platform, execution_mode, account_id, size = 'default' }) {
  if (!platform && !execution_mode && !account_id) return null
  const meta = EXEC_MODE_META[execution_mode] || { color: 'default', label: (execution_mode || 'UNKNOWN').toUpperCase(), tip: '' }
  const parts = []
  if (platform) parts.push(platform)
  if (account_id) parts.push(account_id)
  const label = parts.join(' · ')
  return (
    <Tooltip title={meta.tip || ''}>
      <Space size={4} style={{ fontSize: size === 'small' ? 11 : 12 }}>
        <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
        {label && <Tag>{label}</Tag>}
      </Space>
    </Tooltip>
  )
}

// ----------------------------- 影响可视化 ----------------------------- //
function ImpactView({ impact }) {
  if (!impact) return null
  const f = (v) => (typeof v === 'number' ? v.toFixed(2) : v)
  const rows = []
  if (impact.delta_roi !== undefined)
    rows.push({ k: 'ΔROI', v: impact.delta_roi, good: impact.delta_roi >= 0 })
  if (impact.delta_spend !== undefined)
    rows.push({ k: 'ΔSpend', v: impact.delta_spend, good: impact.delta_spend <= 0 })
  if (impact.delta_installs !== undefined)
    rows.push({ k: 'ΔInstalls', v: impact.delta_installs, good: impact.delta_installs >= 0 })
  if (impact.horizon)
    rows.push({ k: '窗口', v: impact.horizon + 'd', good: true })
  if (!rows.length) return null
  return (
    <div style={{ background: '#f6ffed', borderRadius: 4, padding: '8px 12px', marginTop: 8 }}>
      <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>预测影响（控制 vs 处理）</div>
      <Space wrap>
        {rows.map((it) => (
          <Tag key={it.k} color={it.good ? 'green' : 'red'}>
            {it.k}: {f(it.v)}
          </Tag>
        ))}
      </Space>
    </div>
  )
}

// ----------------------------- 单步渲染 ----------------------------- //
function StepView({ step, loading, onApprove }) {
  const meta = KIND_META[step.kind] || { emoji: '•', color: '#000', label: '' }

  if (step.kind === 'approval') {
    const pending = step.status === 'proposed'
    const prov = step.result?.provenance
    return (
      <Card size="small" style={{ borderLeft: '4px solid #faad14', background: '#fffbe6', marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          <Space wrap>
            <Tag color="orange" icon={<SafetyOutlined />}>⏳ 待审批 {step.risk_level || ''}</Tag>
            <Text strong>{step.text}</Text>
          </Space>
          {prov && (
            <ProvenanceTag platform={prov.platform} execution_mode={prov.execution_mode} account_id={prov.account_id} />
          )}
          {pending ? (
            <Space>
              <Button type="primary" size="small" loading={loading}
                icon={<CheckCircleOutlined />} onClick={() => onApprove(step.id, true)}>
                批准执行
              </Button>
              <Button danger size="small" onClick={() => onApprove(step.id, false, '人工拒绝')}>
                拒绝
              </Button>
            </Space>
          ) : (
            <Tag color={step.status === 'approved' ? 'green' : 'red'}>
              {step.status === 'approved' ? '已批准 · Agent 续跑' : '已驳回 · 重新规划'}
            </Tag>
          )}
        </Space>
      </Card>
    )
  }

  if (step.kind === 'reasoning') {
    const thinking = step.status === 'thinking'
    return (
      <Card size="small" style={{ borderLeft: '4px solid #722ed1', background: '#f9f0ff', marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <Space wrap>
            <Tag color="purple" icon={<span>🧠</span>}>{thinking ? '思考中…' : '思考过程'}</Tag>
            {thinking && <Spin size="small" />}
          </Space>
          <div style={{ maxHeight: 300, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                        fontSize: 13, lineHeight: 1.7, color: '#333',
                        background: '#fff', borderRadius: 4, padding: '8px 10px', border: '1px solid #efdbff' }}>
            {step.text}
          </div>
        </Space>
      </Card>
    )
  }

  if (step.kind === 'thought') {
    return <div style={{ margin: '8px 0', color: '#595959', fontStyle: 'italic' }}>{meta.emoji} {step.text}</div>
  }

  if (step.kind === 'observation') {
    return <div style={{ margin: '4px 0 4px 20px', color: '#8c8c8c', fontSize: 13 }}>{meta.emoji} {step.text}</div>
  }

  if (step.kind === 'action') {
    return (
      <Card size="small" style={{ borderLeft: '4px solid #52c41a', marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <Space wrap>
            <Tag color="green">{meta.emoji} 已执行</Tag>
            {step.tool && <Tag>{step.tool}</Tag>}
            {step.risk_level && <Tag color="blue">{step.risk_level}</Tag>}
            {step.result?.execution_mode && (
              <ProvenanceTag
                platform={step.result?.platform}
                execution_mode={step.result?.execution_mode}
                account_id={step.result?.account_id}
                size="small"
              />
            )}
          </Space>
          <div>{step.text}</div>
          <ImpactView impact={step.result?.impact} />
        </Space>
      </Card>
    )
  }

  if (step.kind === 'final') {
    return <Alert type="success" showIcon message="🏁 结论" description={step.text} style={{ marginBottom: 12 }} />
  }

  return <div style={{ margin: '4px 0' }}>• {step.text}</div>
}

// ----------------------------- 策略卡片 ----------------------------- //
function StrategyCard({ strategy }) {
  if (!strategy || !strategy.rules || !Object.keys(strategy.rules).length) {
    return <Empty description="暂无已学策略（先跑几轮目标，再点『学习策略』）" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  const LABELS = {
    budget_increase_cap: '加预算增幅上限 (%)',
    pause_roi_threshold: '暂停 ROI 阈值',
    rotate_when_roi_below: '换素材触发下限 (ROI)',
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      {Object.entries(strategy.rules).map(([key, r]) => (
        <Card key={key} size="small" style={{ background: '#fafafa' }}>
          <div style={{ fontWeight: 500 }}>{LABELS[key] || key}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <Text strong style={{ fontSize: 18, color: '#1890ff' }}>{r.value}</Text>
            <Tooltip title={`置信度（样本 ${r.n_samples}）`}>
              <Progress
                percent={Math.round((r.confidence || 0) * 100)}
                size="small" style={{ width: 90, margin: 0 }} />
            </Tooltip>
            <Tag>{r.n_samples} 样本</Tag>
          </div>
          <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{r.source}</div>
        </Card>
      ))}
    </Space>
  )
}

// ----------------------------- 主动自治面板 ----------------------------- //
function AutonomyPanel({ status, alerts, loading, onScan, onToggle, onApprove, onViewSession }) {
  const tag = (s) => ALERT_STATUS[s] || { color: 'default', label: s }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      {/* 监控状态条 */}
      <Card size="small" style={{ background: '#fafafa' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Badge status={status?.enabled ? 'processing' : 'default'} />
            <Text strong>主动巡检</Text>
            <Tag color={status?.enabled ? 'green' : 'default'}>
              {status?.enabled ? `运行中 · 每 ${status?.interval_seconds ?? '-'}s` : '已停止'}
            </Tag>
          </Space>
          <Switch
            checked={!!status?.enabled}
            checkedChildren="开" unCheckedChildren="关"
            onChange={(v) => onToggle(v)}
          />
        </div>
        <div style={{ fontSize: 12, color: '#888', marginTop: 6 }}>
          最近扫描：{status?.last_scan_at || '（暂无）'} · 待审批：
          <Text strong style={{ color: '#fa8c16' }}> {status?.pending ?? 0} </Text>条
          {' '}· 平台：{status?.platform}
          {status?.execution_mode && (
            <>
              {' '}·{' '}
              <ProvenanceTag platform={status.platform} execution_mode={status.execution_mode} size="small" />
            </>
          )}
        </div>
      </Card>

      <Button icon={<ScanOutlined />} loading={loading} block onClick={onScan}>
        立即巡检一次
      </Button>

      {/* 告警流 */}
      <div style={{ maxHeight: '42vh', overflowY: 'auto', paddingRight: 4 }}>
        {!alerts || alerts.length === 0 ? (
          <Empty description="暂无告警（系统未发现异常）" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          alerts.map((a) => {
            const an = a.anomaly || {}
            const st = tag(a.status)
            const pending = a.status === 'pending_approval'
            const metrics = an.metrics ? Object.entries(an.metrics)
              .map(([k, v]) => `${k}=${typeof v === 'number' ? (Math.round(v * 100) / 100) : v}`)
              .join('  ') : ''
            return (
              <Card key={a.id} size="small" style={{ marginBottom: 10, borderLeft: `4px solid ${SEVERITY_COLOR[an.severity] || '#ddd'}` }}>
                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                  <Space wrap>
                    <Tag color={SEVERITY_COLOR[an.severity] || 'default'}>
                      <BellOutlined /> {an.title}
                    </Tag>
                    <Tag color={st.color}>{st.label}</Tag>
                  </Space>
                  {an.detail && <div style={{ fontSize: 12, color: '#666' }}>{an.detail}</div>}
                  {metrics && <div style={{ fontSize: 11, color: '#999' }}>{metrics}</div>}
                  {a.resolution && !pending && (
                    <div style={{ fontSize: 12 }}>
                      <Text type="secondary">处置：{a.resolution}</Text>
                    </div>
                  )}
                  <Space wrap>
                    {pending && a.session_id && a.step_id && (
                      <>
                        <Button type="primary" size="small" icon={<CheckCircleOutlined />}
                          onClick={() => onApprove(a, true)}>
                          批准
                        </Button>
                        <Button danger size="small" onClick={() => onApprove(a, false, '人工拒绝')}>
                          驳回
                        </Button>
                      </>
                    )}
                    {a.session_id && (
                      <Button size="small" icon={<EyeOutlined />} onClick={() => onViewSession(a.session_id)}>
                        查看会话
                      </Button>
                    )}
                  </Space>
                </Space>
              </Card>
            )
          })
        )}
      </div>
    </Space>
  )
}

// ----------------------------- 主页面 ----------------------------- //
function AgentConsole() {
  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [session, setSession] = useState(null)
  const [goal, setGoal] = useState('')
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [strategy, setStrategy] = useState(null)
  const [reflectText, setReflectText] = useState(null)
  const [reflectLoading, setReflectLoading] = useState(false)
  const scrollRef = useRef(null)

  // 主动自治 state
  const [autoStatus, setAutoStatus] = useState(null)
  const [autoAlerts, setAutoAlerts] = useState([])
  const [autoLoading, setAutoLoading] = useState(false)
  const autoTimer = useRef(null)
  const esRef = useRef(null)

  // 初始加载：会话列表 + 已学策略 + 主动自治状态
  useEffect(() => { refreshSessions(); refreshStrategy(); refreshAutonomy() }, [])

  // 会话更新后滚动到底部
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [session])

  // 轮询主动自治状态（反映调度器周期扫描结果）
  useEffect(() => {
    autoTimer.current = setInterval(() => refreshAutonomy(), 15000)
    return () => clearInterval(autoTimer.current)
  }, [])

  // Agent 运行实时流：用 SSE 订阅会话步骤（后端 Loop 在后台执行，逐步推送
  // thought/observation/action…，避免整轮跑完才一次性返回）。EventSource 自动重连。
  // Phase 2.2：先用 JWT 换一次性 ticket，再拿 ticket 打开 SSE；长期 JWT 不再进 URL。
  useEffect(() => {
    if (!activeId) return
    let es = null
    let cancelled = false
    ;(async () => {
      let ticket = ''
      try {
        const resp = await agentAPI.createStreamTicket(activeId)
        ticket = resp?.ticket || ''
      } catch (e) {
        // ticket 端点不可用（如后端还没升级）：留空即空 ticket，后端会返回 401
        console.warn('createStreamTicket failed:', e?.response?.status)
      }
      if (cancelled) return
      const url = `/api/v1/agent/sessions/${activeId}/stream?ticket=${encodeURIComponent(ticket)}`
      es = new EventSource(url)
      esRef.current = es
      wireStreamHandlers(es)
    })()
    return () => {
      cancelled = true
      if (es) es.close()
      esRef.current = null
    }
    // wireStreamHandlers 定义在下方 useEffect 之外的常规函数中
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  function wireStreamHandlers(es) {
    es.addEventListener('snapshot', (e) => {
      try {
        const d = JSON.parse(e.data)
        setSession((s) => ({
          ...(s || { id: activeId }),
          steps: d.steps || [],
          status: d.status,
          platform: d.provenance?.platform ?? s?.platform,
          execution_mode: d.provenance?.execution_mode ?? s?.execution_mode,
          account_id: d.provenance?.account_id ?? s?.account_id,
        }))
      } catch (_) { /* ignore */ }
    })
    es.addEventListener('step', (e) => {
      try {
        const step = JSON.parse(e.data)
        setSession((s) => {
          if (!s) return s
          const idx = s.steps.findIndex((x) => x.id === step.id)
          if (idx >= 0) {
            // 已存在（如思考步骤流式增长）：按 id 原地更新
            const steps = s.steps.slice()
            steps[idx] = { ...steps[idx], ...step }
            return { ...s, steps }
          }
          return { ...s, steps: [...s.steps, step] }
        })
      } catch (_) { /* ignore */ }
    })
    es.addEventListener('status', (e) => {
      try {
        const d = JSON.parse(e.data)
        setSession((s) => (s ? { ...s, status: d.status } : s))
      } catch (_) { /* ignore */ }
    })
    es.addEventListener('end', (e) => {
      try {
        const d = JSON.parse(e.data)
        setSession((s) => (s ? { ...s, status: d.status } : s))
      } catch (_) { /* ignore */ }
      es.close()  // 终态：关闭流
    })
    es.onerror = () => {
      // EventSource 会自动重连；终态会话由 end 事件关闭，这里不主动关闭
    }
  }

  const refreshSessions = async () => {
    try {
      const list = await agentAPI.listSessions(APP_ID)
      setSessions(list || [])
    } catch (e) { /* 静默：后端未启动时不阻塞 UI */ }
  }

  const refreshStrategy = async () => {
    try { setStrategy(await agentAPI.getStrategy()) } catch (e) { /* ignore */ }
  }

  const refreshAutonomy = async () => {
    try {
      const [st, al] = await Promise.all([
        agentAPI.autonomyStatus(),
        agentAPI.autonomyAlerts(APP_ID),
      ])
      setAutoStatus(st)
      setAutoAlerts(al || [])
    } catch (e) { /* ignore */ }
  }

  const handleStart = async () => {
    if (!goal.trim()) { message.warning('请输入一个目标'); return }
    setLoading(true)
    try {
      const s = await agentAPI.createSession(goal, APP_ID)
      setSession(s); setActiveId(s.id); setGoal('')
      setSessions((prev) => [s, ...prev.filter((x) => x.id !== s.id)])
      message.success('Agent 已启动')
    } catch (e) {
      message.error('启动失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setLoading(false) }
  }

  const handleApprove = async (stepId, approved, reason) => {
    if (!activeId) return
    setLoading(true)
    try {
      const s = await agentAPI.approve(activeId, stepId, approved, reason)
      setSession(s); await refreshSessions()
      message.success(approved ? '已批准 · Agent 继续执行' : '已驳回 · Agent 重新规划')
    } catch (e) {
      message.error('审批失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setLoading(false) }
  }

  const handleStop = async () => {
    if (!activeId) return
    setLoading(true)
    try {
      await agentAPI.abortSession(activeId)
      message.info('已请求中断，Agent 将停止当前循环')
    } catch (e) {
      message.error('中断失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setLoading(false) }
  }

  const handleSend = async () => {
    if (!activeId || !msg.trim()) return
    setLoading(true)
    try {
      if (session?.status === 'running') {
        // 运行中途发新指令：中断当前 Loop 并按新方向续跑（SSE 同会话无缝继续）
        await agentAPI.redirectSession(activeId, msg)
        setMsg('')
        message.info('已改向：Agent 将按新指令继续')
      } else {
        const s = await agentAPI.sendMessage(activeId, msg)
        setSession(s); setMsg('')
      }
      await refreshSessions()
    } catch (e) {
      message.error('发送失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setLoading(false) }
  }

  const handleSwitch = async (id) => {
    setActiveId(id); setReflectText(null)
    try { setSession(await agentAPI.getSession(id)) } catch (e) { message.error('加载会话失败') }
  }

  const handleNew = () => { setActiveId(null); setSession(null); setReflectText(null) }

  const handleReflect = async () => {
    setReflectLoading(true); setReflectText(null)
    try {
      const r = await agentAPI.reflect()
      setReflectText(r)
    } catch (e) {
      message.error('复盘失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setReflectLoading(false) }
  }

  const handleLearn = async () => {
    try {
      const r = await agentAPI.learnStrategy()
      message.success('策略已学习：' + (r.note || '无新学习'))
      await refreshStrategy()
    } catch (e) {
      message.error('学习失败：' + (e.response?.data?.detail || '未知错误'))
    }
  }

  const handleReset = async () => {
    try {
      await agentAPI.resetStrategy()
      message.success('策略已重置为硬编码默认')
      await refreshStrategy()
    } catch (e) { message.error('重置失败') }
  }

  // —— 主动自治 handlers ——
  const handleAutonomyScan = async () => {
    setAutoLoading(true)
    try {
      const r = await agentAPI.autonomyScan(APP_ID)
      await refreshAutonomy()
      const s = r.summary || {}
      message.success(`巡检完成：自动处置 ${s.auto_executed || 0} · 待审批 ${s.pending_approval || 0} · 仅通知 ${s.no_action || 0}`)
    } catch (e) {
      message.error('巡检失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setAutoLoading(false) }
  }

  const handleAutonomyToggle = async (enabled) => {
    try {
      await agentAPI.autonomyToggle(enabled)
      await refreshAutonomy()
      message.success(enabled ? '主动自治已开启' : '主动自治已停止')
    } catch (e) {
      message.error('操作失败：' + (e.response?.data?.detail || '未知错误'))
    }
  }

  const handleAutonomyApprove = async (alert, approved, reason) => {
    if (!alert.session_id || !alert.step_id) return
    setAutoLoading(true)
    try {
      await agentAPI.approve(alert.session_id, alert.step_id, approved, reason)
      await refreshAutonomy(); await refreshSessions()
      message.success(approved ? '已批准主动提案' : '已驳回主动提案')
    } catch (e) {
      message.error('审批失败：' + (e.response?.data?.detail || '未知错误'))
    } finally { setAutoLoading(false) }
  }

  const statusTag = session ? (SESSION_STATUS[session.status] || { color: 'default', label: session.status }) : null

  return (
    <div>
      {/* 顶部标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            <RobotOutlined style={{ color: '#1890ff', marginRight: 8 }} />
            智能体控制台
          </Title>
          <Text type="secondary">目标驱动 · 自主循环 · 人在环审批 · 记忆/策略自演化 · 主动自治（Phase 1~4）</Text>
        </div>
        <Space wrap>
          <Select
            placeholder="切换会话"
            style={{ width: 240 }}
            value={activeId || undefined}
            onChange={handleSwitch}
            options={sessions.map((s) => ({
              value: s.id,
              label: `${(s.goal || '').slice(0, 18)}${s.status === 'awaiting_approval' ? ' · ⏳待审批' : ''}`,
            }))}
          />
          <Button icon={<PlusOutlined />} onClick={handleNew}>新会话</Button>
          <Button icon={<ReloadOutlined />} onClick={refreshSessions}>刷新</Button>
        </Space>
      </div>

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* 左：对话区 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!session ? (
            <Card>
              <Title level={5}>给 Agent 一个目标</Title>
              <Text type="secondary">
                用自然语言描述你想要的投放结果（例如「把美国区 ROAS 提上来」），Agent 会自主拆解成多步动作、
                对高风险动作请求你的批准，并在执行后回采影响。
              </Text>
              <TextArea
                rows={4}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="例如：暂停 ROI 低于 0.5 的 campaign，给 ROI 最高的加预算 20%..."
                style={{ margin: '12px 0' }}
                onPressEnter={(e) => e.shiftKey || handleStart()}
              />
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary" style={{ marginRight: 8 }}>试试：</Text>
                {SAMPLE_GOALS.map((g, i) => (
                  <Tag key={i} style={{ cursor: 'pointer', marginBottom: 6 }} onClick={() => setGoal(g)}>{g}</Tag>
                ))}
              </div>
              <Button type="primary" icon={<ThunderboltOutlined />} loading={loading} onClick={handleStart}>
                启动 Agent
              </Button>
            </Card>
          ) : (
            <Card
              title={
                <Space wrap>
                  <span>目标：{session.goal}</span>
                  {statusTag && <Tag color={statusTag.color}>{statusTag.label}</Tag>}
                  <ProvenanceTag
                    platform={session.platform}
                    execution_mode={session.execution_mode}
                    account_id={session.account_id}
                  />
                  {session.status === 'running' && (
                    <Tag color="processing" style={{ marginLeft: 4 }}>
                      <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#1890ff', marginRight: 6, animation: 'ant-status-processing 1.2s infinite' }} />
                      实时流式
                    </Tag>
                  )}
                </Space>
              }
              extra={<Button size="small" onClick={handleNew}>新建</Button>}
            >
              <div ref={scrollRef} style={{ maxHeight: '56vh', overflowY: 'auto', paddingRight: 8 }}>
                {session.steps.map((step) => (
                  <StepView key={step.id} step={step} loading={loading} onApprove={handleApprove} />
                ))}
              </div>
              <Divider style={{ margin: '12px 0' }} />
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder={session.status === 'awaiting_approval' ? '先审批上方动作，或补充指令…' : '继续追问 / 追加指令…'}
                  value={msg}
                  onChange={(e) => setMsg(e.target.value)}
                  onPressEnter={handleSend}
                  disabled={loading}
                />
                {session.status === 'running' && (
                  <Button danger icon={<StopOutlined />} loading={loading} onClick={handleStop}>停止</Button>
                )}
                <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={handleSend}>
                  {session.status === 'running' ? '改向继续' : '发送'}
                </Button>
              </Space.Compact>
            </Card>
          )}
        </div>

        {/* 右：智能体大脑 / 主动自治（Tabs） */}
        <div style={{ width: 360, flexShrink: 0 }}>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Tabs
              defaultActiveKey="brain"
              items={[
                {
                  key: 'brain',
                  label: <span><AimOutlined /> 智能体大脑</span>,
                  children: (
                    <Space direction="vertical" style={{ width: '100%' }} size={12}>
                      <div>
                        <Title level={5} style={{ marginTop: 0 }}>🎯 已学策略</Title>
                        <StrategyCard strategy={strategy} />
                        <Space style={{ marginTop: 12 }} wrap>
                          <Button size="small" type="primary" onClick={handleLearn}>学习策略</Button>
                          <Button size="small" danger onClick={handleReset}>重置策略</Button>
                        </Space>
                      </div>
                      <Divider style={{ margin: '4px 0' }} />
                      <div>
                        <Title level={5}>🧠 经验复盘</Title>
                        <Button size="small" icon={<ReloadOutlined />} loading={reflectLoading} onClick={handleReflect}>
                          复盘记忆
                        </Button>
                        {reflectText && (
                          <div style={{ marginTop: 12 }}>
                            <Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 13, marginBottom: 8 }}>
                              {reflectText.summary}
                            </Paragraph>
                            {reflectText.rules?.length > 0 && (
                              <Collapse size="small" items={reflectText.rules.map((rule, i) => ({
                                key: i, label: `规则 ${i + 1}`, children: <span style={{ fontSize: 13 }}>{rule}</span>,
                              }))} />
                            )}
                            <div style={{ fontSize: 11, color: '#999', marginTop: 6 }}>
                              基于 {reflectText.episodes_count || 0} 次动作经历
                            </div>
                          </div>
                        )}
                      </div>
                    </Space>
                  ),
                },
                {
                  key: 'auto',
                  label: <span><BellOutlined /> 主动自治</span>,
                  children: (
                    <AutonomyPanel
                      status={autoStatus}
                      alerts={autoAlerts}
                      loading={autoLoading}
                      onScan={handleAutonomyScan}
                      onToggle={handleAutonomyToggle}
                      onApprove={handleAutonomyApprove}
                      onViewSession={handleSwitch}
                    />
                  ),
                },
              ]}
            />
          </Card>

          <Card size="small" title="📌 说明">
            <Paragraph style={{ fontSize: 12, color: '#666', margin: 0 }}>
              · L0 动作（如换素材）自动执行；L1/L2 动作需你在此页面批准。<br />
              · 每个写动作执行后都会回采 2h/24h/7d 影响，沉淀进记忆。<br />
              · 「学习策略」把记忆编译为可复用的参数（跨账户/重启不丢），让 Agent 越做越准。<br />
              · 「主动自治」：系统周期巡检，自动处置低风险异常、把高风险提案推给你审批、账户被封主动告警。
            </Paragraph>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default AgentConsole
