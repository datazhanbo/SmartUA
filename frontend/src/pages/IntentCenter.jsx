import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card,
  Input,
  Button,
  Space,
  Tag,
  List,
  Avatar,
  Statistic,
  Row,
  Col,
  Modal,
  message,
  Timeline,
  Badge,
  Descriptions
} from 'antd'
import { MOCK_INTENT_EXECUTIONS, MOCK_CAMPAIGNS, getCampaignById } from '../data/mockData'
import { 
  ThunderboltOutlined, 
  SendOutlined, 
  CheckCircleOutlined,
  StopOutlined,
  ClockCircleOutlined,
  RobotOutlined,
  UserOutlined,
  WarningOutlined,
  SafetyCertificateOutlined
} from '@ant-design/icons'
import { intentAPI } from '../api'

const { TextArea } = Input

// 风险等级配置
const RISK_LEVEL_CONFIG = {
  L0: { color: 'green', label: '自动执行', desc: '无需审批，立即执行', icon: <CheckCircleOutlined /> },
  L1: { color: 'blue', label: '一键确认', desc: '10分钟超时自动执行', icon: <ClockCircleOutlined /> },
  L2: { color: 'orange', label: '人工审核', desc: '必须人工确认才能执行', icon: <WarningOutlined /> },
  L3: { color: 'red', label: '仅建议', desc: '仅供参考，需完全人工操作', icon: <SafetyCertificateOutlined /> },
}

// 示例意图提示
const SAMPLE_INTENTS = [
  '把 ROI 低于 0.5 的 Campaign 暂停',
  '给 ROI > 1.2 的 Campaign 加预算 20%',
  '查看美国地区表现最差的 3 个计划',
  '轮换 ROI 低于平均的素材',
  '检查今日异常告警',
  '导出上周投放数据报表',
]

function IntentCenter({ user }) {
  const navigate = useNavigate()
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const [parseResult, setParseResult] = useState(null)
  const [executions, setExecutions] = useState([])
  const [modalVisible, setModalVisible] = useState(false)
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [currentExecution, setCurrentExecution] = useState(null)
  const [currentApp] = useState({ id: 1 })

  useEffect(() => {
    loadMockExecutions()
  }, [])

  const loadMockExecutions = () => {
    setExecutions(MOCK_INTENT_EXECUTIONS)
  }

  const handleParse = async () => {
    if (!inputText.trim()) {
      message.warning('请输入操作指令')
      return
    }

    setLoading(true)
    try {
      const result = await intentAPI.parse(inputText, currentApp.id)
      setParseResult(result)
      setModalVisible(true)
    } catch (error) {
      message.error('解析失败：' + (error.response?.data?.detail || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  const handleExecute = async () => {
    if (!parseResult) return

    try {
      const result = await intentAPI.execute(inputText, currentApp.id)
      message.success('意图执行已提交，执行 ID: ' + result.execution_id)
      setModalVisible(false)
      setInputText('')
      setParseResult(null)
      loadMockExecutions()
    } catch (error) {
      message.error('执行失败')
    }
  }

  const handleApprove = async (executionId, approved) => {
    try {
      await intentAPI.approve(executionId, approved, approved ? '' : '人工拒绝')
      message.success(approved ? '已批准执行' : '已拒绝执行')
      loadMockExecutions()
    } catch (error) {
      message.error('操作失败')
    }
  }

  const handleQuickIntent = (text) => {
    setInputText(text)
  }

  const handleViewDetail = (execution) => {
    setCurrentExecution(execution)
    setDetailModalVisible(true)
  }

  const renderRiskInfo = (riskLevel) => {
    const config = RISK_LEVEL_CONFIG[riskLevel] || RISK_LEVEL_CONFIG.L2
    return (
      <Space>
        <Tag color={config.color} icon={config.icon}>
          {config.label}
        </Tag>
        <span style={{ color: '#666' }}>{config.desc}</span>
      </Space>
    )
  }

  const executionColumns = [
    {
      title: '操作历史',
      dataIndex: 'intent',
      key: 'intent',
      render: (text, record) => (
        <div>
          <div style={{ fontWeight: 500 }}>{text}</div>
          <div style={{ fontSize: 12, color: '#999' }}>{record.created_at}</div>
        </div>
      )
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      render: (val) => renderRiskInfo(val)
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (val) => {
        const statusMap = {
          success: <Tag color="green">执行成功</Tag>,
          pending_approval: <Tag color="orange">待审批</Tag>,
          running: <Tag color="blue">执行中</Tag>,
          failed: <Tag color="red">执行失败</Tag>,
        }
        return statusMap[val] || val
      }
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => {
        if (record.status === 'pending_approval') {
          return (
            <Space>
              <Button size="small" type="primary" onClick={() => handleApprove(record.id, true)}>
                批准
              </Button>
              <Button size="small" danger onClick={() => handleApprove(record.id, false)}>
                拒绝
              </Button>
            </Space>
          )
        }
        return <Button size="small">查看详情</Button>
      }
    }
  ]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, marginBottom: 8 }}>⚡ 意图操作中心</h2>
        <p style={{ color: '#666', margin: 0 }}>用自然语言描述您的投放操作，AI 自动识别意图并执行</p>
      </div>

      <Row gutter={16}>
        {/* 左侧：意图输入 + 风险说明 */}
        <Col span={16}>
          <Card 
            title={
              <Space>
                <RobotOutlined />
                <span>自然语言操作</span>
                <Tag color="blue">Rule-based 模式</Tag>
              </Space>
            }
            extra={
              <Button type="primary" onClick={handleParse} loading={loading} icon={<SendOutlined />}>
                解析意图
              </Button>
            }
          >
            <TextArea
              rows={4}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="请输入您的投放操作指令，例如：把 ROI 低于 0.5 的 Campaign 暂停..."
              style={{ marginBottom: 16 }}
              onPressEnter={(e) => e.shiftKey || handleParse()}
            />

            <div style={{ marginBottom: 16 }}>
              <span style={{ color: '#666', marginRight: 8 }}>快捷指令：</span>
              {SAMPLE_INTENTS.map((item, idx) => (
                <Tag 
                  key={idx} 
                  style={{ cursor: 'pointer', marginBottom: 8 }}
                  onClick={() => handleQuickIntent(item)}
                >
                  {item}
                </Tag>
              ))}
            </div>

            {/* 安全分级说明 */}
            <Card size="small" title="🔐 操作安全分级机制" style={{ background: '#fafafa' }}>
              <Row gutter={16}>
                {Object.entries(RISK_LEVEL_CONFIG).map(([level, config]) => (
                  <Col span={6} key={level}>
                    <Space direction="vertical" size={0}>
                      <Tag color={config.color} icon={config.icon}>{level}: {config.label}</Tag>
                      <span style={{ fontSize: 12, color: '#666' }}>{config.desc}</span>
                    </Space>
                  </Col>
                ))}
              </Row>
            </Card>
          </Card>

          {/* 执行历史 */}
          <Card 
            title="📋 操作历史 & 待审批" 
            style={{ marginTop: 16 }}
            extra={<Button type="link">查看全部</Button>}
          >
            <List
              dataSource={executions}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleViewDetail(item)}
                  actions={
                    item.status === 'pending_approval' ? [
                      <Button key="approve" size="small" type="primary" onClick={(e) => { e.stopPropagation(); handleApprove(item.id, true); }}>
                        批准
                      </Button>,
                      <Button key="reject" size="small" danger onClick={(e) => { e.stopPropagation(); handleApprove(item.id, false); }}>
                        拒绝
                      </Button>
                    ] : [
                      <Button key="detail" size="small" type="link" onClick={(e) => { e.stopPropagation(); handleViewDetail(item); }}>
                        详情
                      </Button>
                    ]
                  }
                >
                  <List.Item.Meta
                    avatar={
                      <Badge status={item.status === 'success' ? 'success' : item.status === 'pending_approval' ? 'warning' : 'default'}>
                        <Avatar icon={<ThunderboltOutlined />} />
                      </Badge>
                    }
                    title={
                      <Space>
                        <span style={{ fontWeight: 500 }}>{item.intent}</span>
                        <Tag color={RISK_LEVEL_CONFIG[item.risk_level]?.color}>{item.risk_level}</Tag>
                      </Space>
                    }
                    description={
                      <div>
                        <div style={{ marginBottom: 4 }}>{item.created_at}</div>
                        <div style={{ fontSize: 12, color: '#666' }}>
                          影响 {item.affected_count} 个 Campaign · 总花费 ${item.total_spend?.toLocaleString()}
                        </div>
                        <div style={{ marginTop: 4 }}>
                          {item.affected_campaigns?.slice(0, 2).map((camp, idx) => (
                            <Tag
                              key={idx}
                              size="small"
                              color="blue"
                              style={{
                                fontSize: 11,
                                marginRight: 4,
                                marginBottom: 2,
                                cursor: camp.status?.includes('待创建') ? 'default' : 'pointer'
                              }}
                              onClick={(e) => {
                                e.stopPropagation()
                                if (!camp.status?.includes('待创建')) {
                                  const campaignId = camp.id.replace('camp_', '').replace('new_', '')
                                  navigate(`/campaign/${campaignId}`)
                                }
                              }}
                            >
                              {camp.name}
                              {camp.roi && ` · ROI: ${camp.roi}`}
                              {camp.status?.includes('待创建') && ' (待创建)'}
                            </Tag>
                          ))}
                          {item.affected_campaigns?.length > 2 && (
                            <Tag size="small" style={{ fontSize: 11 }}>
                              +{item.affected_campaigns.length - 2} 更多
                            </Tag>
                          )}
                        </div>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        {/* 右侧：统计 + 待处理 */}
        <Col span={8}>
          <Card>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic title="今日操作" value={12} suffix="次" />
              </Col>
              <Col span={12}>
                <Statistic title="自动执行" value={8} suffix="次" valueStyle={{ color: '#52c41a' }} />
              </Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 16 }}>
              <Col span={12}>
                <Statistic
                  title="待审批"
                  value={executions.filter(e => e.status === 'pending_approval').length}
                  suffix="项"
                  valueStyle={{ color: '#faad14' }}
                />
              </Col>
              <Col span={12}>
                <Statistic title="节省花费" value={12500} prefix="$" valueStyle={{ color: '#1890ff' }} />
              </Col>
            </Row>
          </Card>

          <Card title="⏰ 待我审批" style={{ marginTop: 16 }}>
            <Timeline>
              {executions.filter(e => e.status === 'pending_approval').map((item) => (
                <Timeline.Item
                  key={item.id}
                  color={item.risk_level === 'L1' ? 'blue' : 'orange'}
                >
                  <div style={{ cursor: 'pointer' }} onClick={() => handleViewDetail(item)}>
                    <div style={{ fontWeight: 500 }}>{item.intent}</div>
                    <div style={{ fontSize: 12, color: '#666' }}>
                      风险等级 {item.risk_level} · 影响 {item.affected_count} 个 Campaign
                    </div>
                    <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                      {item.affected_campaigns?.slice(0, 2).map((c, idx) => (
                        <span
                          key={idx}
                          style={{
                            color: c.status?.includes('待创建') ? '#999' : '#1890ff',
                            cursor: c.status?.includes('待创建') ? 'default' : 'pointer'
                          }}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (!c.status?.includes('待创建')) {
                              const campaignId = c.id.replace('camp_', '').replace('new_', '')
                              navigate(`/campaign/${campaignId}`)
                            }
                          }}
                        >
                          {c.name}{idx < Math.min(item.affected_campaigns.length - 1, 1) ? ', ' : ''}
                        </span>
                      ))}
                      {item.affected_campaigns?.length > 2 && ` 等${item.affected_campaigns.length}个`}
                    </div>
                    <Space style={{ marginTop: 8 }}>
                      <Button size="small" type="primary" onClick={(e) => { e.stopPropagation(); handleApprove(item.id, true); }}>
                        批准
                      </Button>
                      <Button size="small" onClick={(e) => { e.stopPropagation(); handleApprove(item.id, false); }}>
                        拒绝
                      </Button>
                      <Button size="small" type="link" onClick={(e) => { e.stopPropagation(); handleViewDetail(item); }}>
                        查看详情
                      </Button>
                    </Space>
                  </div>
                </Timeline.Item>
              ))}
              {executions.filter(e => e.status === 'pending_approval').length === 0 && (
                <Timeline.Item color="green">
                  <div style={{ color: '#999', textAlign: 'center', padding: '20px 0' }}>
                    ✅ 暂无待审批项
                  </div>
                </Timeline.Item>
              )}
            </Timeline>
          </Card>
        </Col>
      </Row>

      {/* 解析结果弹窗 */}
      <Modal
        title="🤖 AI 意图解析结果"
        open={modalVisible}
        onOk={handleExecute}
        onCancel={() => setModalVisible(false)}
        okText="确认执行"
        cancelText="取消"
        width={700}
      >
        {parseResult && (
          <div>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="意图类型" span={1}>
                <Tag color="blue">{parseResult.intent_class}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="置信度" span={1}>
                {((parseResult.confidence || 0) * 100).toFixed(1)}%
              </Descriptions.Item>
              <Descriptions.Item label="风险等级" span={1}>
                {renderRiskInfo(parseResult.risk_level)}
              </Descriptions.Item>
              <Descriptions.Item label="解析方式" span={1}>
                <Tag>{parseResult.parse_method || 'rule_based'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="影响 Campaign 数" span={2}>
                {parseResult.estimated_impact?.affected_campaign_count || 0} 个
              </Descriptions.Item>
              <Descriptions.Item label="预计节省花费" span={2}>
                ${parseResult.estimated_impact?.daily_spend_reduction || 0} / 天
              </Descriptions.Item>
            </Descriptions>

            {parseResult.suggested_actions?.length > 0 && (
              <div>
                <h4 style={{ marginBottom: 8 }}>📝 建议操作列表</h4>
                <List
                  size="small"
                  dataSource={parseResult.suggested_actions}
                  renderItem={(action) => (
                    <List.Item>
                      <List.Item.Meta
                        title={action.campaign_name}
                        description={`${action.action}: ${action.reason || ''} · 预计节省: $${action.estimated_saving || 0}`}
                      />
                    </List.Item>
                  )}
                />
              </div>
            )}

            {parseResult.approval_deadline && (
              <div style={{ marginTop: 16, padding: 12, background: '#fffbe6', borderRadius: 4 }}>
                <ClockCircleOutlined style={{ marginRight: 8, color: '#faad14' }} />
                此操作将在 10 分钟内超时自动执行，您可在此之前手动批准或拒绝
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* 详情弹窗 */}
      <Modal
        title="📋 意图执行详情"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            关闭
          </Button>
        ]}
        width={800}
      >
        {currentExecution && (
          <div>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="操作意图" span={2}>
                {currentExecution.intent}
              </Descriptions.Item>
              <Descriptions.Item label="风险等级">
                {renderRiskInfo(currentExecution.risk_level)}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {currentExecution.status === 'success' ? <Tag color="green">执行成功</Tag> :
                 currentExecution.status === 'pending_approval' ? <Tag color="orange">待审批</Tag> :
                 <Tag color="blue">{currentExecution.status}</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间" span={2}>
                {currentExecution.created_at}
              </Descriptions.Item>
              <Descriptions.Item label="影响 Campaign 数" span={2}>
                {currentExecution.affected_count} 个
              </Descriptions.Item>
              <Descriptions.Item label="涉及总花费" span={2}>
                ${currentExecution.total_spend?.toLocaleString()}
              </Descriptions.Item>
              {currentExecution.estimated_saving && (
                <Descriptions.Item label="预计节省花费" span={2}>
                  <span style={{ color: '#52c41a', fontWeight: 500 }}>
                    ${currentExecution.estimated_saving.toLocaleString()} / 天
                  </span>
                </Descriptions.Item>
              )}
              {currentExecution.estimated_increment && (
                <Descriptions.Item label="预计增加预算" span={2}>
                  <span style={{ color: '#faad14', fontWeight: 500 }}>
                    ${currentExecution.estimated_increment.toLocaleString()}
                  </span>
                </Descriptions.Item>
              )}
            </Descriptions>

            <h4 style={{ marginBottom: 12 }}>
              📊 {currentExecution.new_campaign ? '新建 Campaign 列表' : '受影响 Campaign 列表'}
            </h4>
            <List
              size="small"
              dataSource={currentExecution.affected_campaigns}
              bordered
              renderItem={(camp) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => {
                    if (!camp.status?.includes('待创建')) {
                      const campaignId = camp.id.replace('camp_', '').replace('new_', '')
                      navigate(`/campaign/${campaignId}`)
                      setDetailModalVisible(false)
                    }
                  }}
                  actions={!camp.status?.includes('待创建') ? [
                    <Button type="link" size="small">
                      查看详情
                    </Button>
                  ] : null}
                >
                  <List.Item.Meta
                    avatar={
                      <Badge dot={camp.status?.includes('待创建')} color="orange">
                        <Avatar size="small" style={{ background: '#1890ff' }}>
                          {camp.name.charAt(0)}
                        </Avatar>
                      </Badge>
                    }
                    title={
                      <Space>
                        <span style={{ fontWeight: 500 }}>{camp.name}</span>
                        {camp.status?.includes('待创建') && (
                          <Tag color="orange" size="small">{camp.status}</Tag>
                        )}
                        {!camp.status?.includes('待创建') && (
                          <span style={{ color: '#1890ff', fontSize: 12 }}>→ 点击跳转</span>
                        )}
                      </Space>
                    }
                    description={
                      <div style={{ fontSize: 12, color: '#666' }}>
                        <Space split="|">
                          <span>ID: {camp.id}</span>
                          {camp.spend && <span>花费: ${camp.spend?.toLocaleString()}</span>}
                          {camp.budget && <span>预算: ${camp.budget?.toLocaleString()}</span>}
                          {camp.roi && <span>ROI: {camp.roi}</span>}
                          {camp.cpi && <span>CPI: ${camp.cpi}</span>}
                          {camp.target_cpi && <span>目标 CPI: ${camp.target_cpi}</span>}
                          {camp.bid_strategy && <span>出价: {camp.bid_strategy}</span>}
                        </Space>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />

            {currentExecution.status === 'pending_approval' && (
              <div style={{ marginTop: 16, textAlign: 'right' }}>
                <Space>
                  <Button danger onClick={() => { handleApprove(currentExecution.id, false); setDetailModalVisible(false); }}>
                    拒绝执行
                  </Button>
                  <Button type="primary" onClick={() => { handleApprove(currentExecution.id, true); setDetailModalVisible(false); }}>
                    批准执行
                  </Button>
                </Space>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

export default IntentCenter
