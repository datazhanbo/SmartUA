import React, { useState, useEffect } from 'react'
import {
  Card,
  Table,
  Tag,
  Space,
  Button,
  Typography,
  Row,
  Col,
  Statistic,
  Tabs,
  Descriptions,
  Badge,
  Select,
  DatePicker,
  message,
  Timeline,
  Empty,
  Spin,
  Divider,
  Tooltip,
  Modal,
  Form,
  Input,
  Switch,
  InputNumber
} from 'antd'
import {
  ApiOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  KeyOutlined
} from '@ant-design/icons'
import axios from 'axios'

const { Title, Text, Paragraph } = Typography
const { TabPane } = Tabs
const { RangePicker } = DatePicker
const { Option } = Select
const { TextArea } = Input

const PLATFORM_INFO = {
  meta: {
    name: 'Meta Ads',
    color: '#1877F2',
    icon: '📘',
    description: 'Facebook/Instagram 广告平台',
    authType: 'oauth2',
    credentialFields: [
      { key: 'access_token', label: 'Access Token', required: true },
      { key: 'app_secret', label: 'App Secret', required: false }
    ]
  },
  google: {
    name: 'Google Ads',
    color: '#4285F4',
    icon: '🔍',
    description: 'Google 广告平台',
    authType: 'oauth2',
    credentialFields: [
      { key: 'client_id', label: 'Client ID', required: true },
      { key: 'client_secret', label: 'Client Secret', required: true },
      { key: 'refresh_token', label: 'Refresh Token', required: true },
      { key: 'developer_token', label: 'Developer Token', required: true },
      { key: 'customer_id', label: 'Customer ID', required: false }
    ]
  },
  appsflyer: {
    name: 'AppsFlyer',
    color: '#FF6B6B',
    icon: '📱',
    description: '移动归因平台',
    authType: 'api_key',
    credentialFields: [
      { key: 'api_key', label: 'API Key', required: true }
    ]
  },
  tiktok: {
    name: 'TikTok Ads',
    color: '#000000',
    icon: '🎵',
    description: 'TikTok 广告平台',
    authType: 'oauth2',
    credentialFields: [
      { key: 'access_token', label: 'Access Token', required: true },
      { key: 'advertiser_id', label: 'Advertiser ID', required: false }
    ]
  }
}

function ConnectorManagement() {
  const [loading, setLoading] = useState(false)
  const [connectors, setConnectors] = useState(null)
  const [runs, setRuns] = useState([])
  const [syncStatus, setSyncStatus] = useState(null)
  const [credentials, setCredentials] = useState([])
  const [activeTab, setActiveTab] = useState('overview')
  const [selectedPlatform, setSelectedPlatform] = useState('meta')
  const [dateRange, setDateRange] = useState(null)
  const [reportType, setReportType] = useState('campaign_daily')
  const [pullLoading, setPullLoading] = useState(false)

  const [credentialModalVisible, setCredentialModalVisible] = useState(false)
  const [editingCredential, setEditingCredential] = useState(null)
  const [credentialForm] = Form.useForm()
  const [credentialLoading, setCredentialLoading] = useState(false)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }

      const [connRes, runsRes, statusRes, credRes] = await Promise.all([
        axios.get('/api/v1/connectors/', { headers }),
        axios.get('/api/v1/connectors/runs?limit=20', { headers }),
        axios.get('/api/v1/connectors/status', { headers }),
        axios.get('/api/v1/connectors/credentials', { headers })
      ])

      setConnectors(connRes.data)
      setRuns(runsRes.data.items)
      setSyncStatus(statusRes.data)
      setCredentials(credRes.data)
    } catch (error) {
      console.error('Load data failed:', error)
    } finally {
      setLoading(false)
    }
  }

  const handlePullData = async () => {
    if (!dateRange || dateRange.length !== 2) {
      message.error('请选择日期范围')
      return
    }

    setPullLoading(true)
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }

      const res = await axios.post('/api/v1/connectors/pull', null, {
        headers,
        params: {
          platform: selectedPlatform,
          date_from: dateRange[0].format('YYYY-MM-DD'),
          date_to: dateRange[1].format('YYYY-MM-DD'),
          report_type: reportType
        }
      })

      message.success(`拉取成功！原始数据: ${res.data.raw_rows} 行, 标准化: ${res.data.normalized_rows} 行`)
      loadData()
    } catch (error) {
      message.error('拉取失败：' + (error.response?.data?.detail || '未知错误'))
    } finally {
      setPullLoading(false)
    }
  }

  const handleSyncDWS = async () => {
    if (!dateRange || dateRange.length !== 2) {
      message.error('请选择日期范围')
      return
    }

    setPullLoading(true)
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }

      const res = await axios.post('/api/v1/connectors/sync/dws', null, {
        headers,
        params: {
          date_from: dateRange[0].format('YYYY-MM-DD'),
          date_to: dateRange[1].format('YYYY-MM-DD')
        }
      })

      message.success(`DWS 聚合成功！更新了 ${res.data.inserted_new} 条记录`)
      loadData()
    } catch (error) {
      message.error('聚合失败：' + (error.response?.data?.detail || '未知错误'))
    } finally {
      setPullLoading(false)
    }
  }

  const handleOpenCredentialModal = (credential = null) => {
    setEditingCredential(credential)
    if (credential) {
      credentialForm.setFieldsValue({
        platform: credential.platform,
        account_name: credential.account_name,
        account_id: credential.account_id,
        sync_frequency: credential.sync_frequency,
        auto_sync_enabled: credential.auto_sync_enabled,
        notes: credential.notes,
        ...credential.credentials_json
      })
    } else {
      credentialForm.resetFields()
    }
    setCredentialModalVisible(true)
  }

  const handleSaveCredential = async () => {
    try {
      const values = await credentialForm.validateFields()
      setCredentialLoading(true)

      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }

      const platformInfo = PLATFORM_INFO[values.platform]
      const credentialFields = platformInfo?.credentialFields || []

      const credentials_json = {}
      credentialFields.forEach(field => {
        if (values[field.key]) {
          credentials_json[field.key] = values[field.key]
        }
      })

      const data = {
        platform: values.platform,
        account_name: values.account_name,
        account_id: values.account_id,
        auth_type: platformInfo?.authType || 'api_key',
        credentials_json,
        sync_frequency: values.sync_frequency || 'daily',
        auto_sync_enabled: values.auto_sync_enabled || false,
        notes: values.notes
      }

      if (editingCredential) {
        await axios.put(`/api/v1/connectors/credentials/${editingCredential.id}`, data, { headers })
        message.success('凭证更新成功')
      } else {
        await axios.post('/api/v1/connectors/credentials', data, { headers })
        message.success('凭证创建成功')
      }

      setCredentialModalVisible(false)
      loadData()
    } catch (error) {
      message.error('保存失败：' + (error.response?.data?.detail || '未知错误'))
    } finally {
      setCredentialLoading(false)
    }
  }

  const handleDeleteCredential = async (id) => {
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }
      await axios.delete(`/api/v1/connectors/credentials/${id}`, { headers })
      message.success('删除成功')
      loadData()
    } catch (error) {
      message.error('删除失败：' + (error.response?.data?.detail || '未知错误'))
    }
  }

  const handleVerifyCredential = async (id) => {
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }
      const res = await axios.post('/api/v1/connectors/credentials/verify', { credential_id: id }, { headers })
      if (res.data.is_verified) {
        message.success('凭证验证成功')
      } else {
        message.error('凭证验证失败')
      }
      loadData()
    } catch (error) {
      message.error('验证失败：' + (error.response?.data?.detail || '未知错误'))
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'success': return <CheckCircleOutlined style={{ color: '#52c41a' }} />
      case 'failed': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      case 'running': return <SyncOutlined spin style={{ color: '#1890ff' }} />
      default: return null
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'success': return 'success'
      case 'failed': return 'error'
      case 'running': return 'processing'
      default: return 'default'
    }
  }

  const renderCredentialFields = () => {
    const platform = credentialForm.getFieldValue('platform') || 'meta'
    const platformInfo = PLATFORM_INFO[platform]

    return (platformInfo?.credentialFields || []).map(field => (
      <Form.Item
        key={field.key}
        name={field.key}
        label={field.label}
        rules={field.required ? [{ required: true, message: `请输入${field.label}` }] : []}
      >
        <Input.Password placeholder={`请输入${field.label}`} />
      </Form.Item>
    ))
  }

  if (loading && !connectors) {
    return (
      <div style={{ padding: 100, textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>加载连接器管理...</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Title level={3} style={{ margin: 0 }}>
            <ApiOutlined /> 连接器管理
          </Title>
        </Space>
        <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="📊 概览" key="overview">
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="可用连接器"
                  value={Object.keys(connectors || {}).length}
                  prefix={<ApiOutlined />}
                  valueStyle={{ color: '#1890ff' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="已配置凭证"
                  value={credentials.length}
                  prefix={<KeyOutlined />}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="最近7天同步任务"
                  value={runs.length}
                  prefix={<CloudUploadOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="成功同步"
                  value={runs.filter(r => r.status === 'success').length}
                  valueStyle={{ color: '#52c41a' }}
                  prefix={<CheckCircleOutlined />}
                />
              </Card>
            </Col>
          </Row>

          <Card title="🔌 可用连接器列表" style={{ marginBottom: 24 }}>
            <Row gutter={16}>
              {Object.entries(connectors || {}).map(([key, info]) => {
                const platformInfo = PLATFORM_INFO[key] || { name: key, color: '#999', icon: '🔌' }
                const hasCredential = credentials.some(c => c.platform === key)
                return (
                  <Col span={8} key={key}>
                    <Card
                      size="small"
                      style={{ marginBottom: 16 }}
                      extra={
                        <Space>
                          <Tag color={hasCredential ? 'success' : 'warning'}>
                            {hasCredential ? '已配置' : '未配置'}
                          </Tag>
                          <Tag color={platformInfo.color}>{info.source_type}</Tag>
                        </Space>
                      }
                    >
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <Space>
                          <span style={{ fontSize: 24 }}>{platformInfo.icon}</span>
                          <Text strong style={{ fontSize: 16 }}>{platformInfo.name}</Text>
                        </Space>
                        <Text type="secondary">{platformInfo.description}</Text>
                        <Descriptions column={1} size="small">
                          <Descriptions.Item label="速率限制">{info.rate_limit} req/hour</Descriptions.Item>
                        </Descriptions>
                        <Button
                          type="primary"
                          size="small"
                          icon={<PlusOutlined />}
                          onClick={() => handleOpenCredentialModal()}
                        >
                          配置凭证
                        </Button>
                      </Space>
                    </Card>
                  </Col>
                )
              })}
            </Row>
          </Card>

          <Card title="🕐 最近同步记录">
            <Table
              dataSource={runs}
              rowKey="id"
              size="small"
              pagination={{ pageSize: 10 }}
              columns={[
                {
                  title: '状态',
                  dataIndex: 'status',
                  key: 'status',
                  width: 80,
                  render: (v) => (
                    <Space>
                      {getStatusIcon(v)}
                      <Tag color={getStatusColor(v)}>{v}</Tag>
                    </Space>
                  )
                },
                { title: '平台', dataIndex: 'connector', key: 'connector', width: 100 },
                { title: '类型', dataIndex: 'report_type', key: 'report_type', width: 120 },
                {
                  title: '日期范围',
                  key: 'range',
                  width: 200,
                  render: (_, r) => `${r.date_from || '-'} ~ ${r.date_to || '-'}`
                },
                { title: '原始行数', dataIndex: 'raw_row_count', key: 'raw', width: 100 },
                { title: '标准化行数', dataIndex: 'normalized_row_count', key: 'norm', width: 120 },
                {
                  title: '同步时间',
                  dataIndex: 'created_at',
                  key: 'created_at',
                  width: 180,
                  render: (v) => new Date(v).toLocaleString()
                },
                {
                  title: '错误',
                  dataIndex: 'error_detail',
                  key: 'error',
                  ellipsis: true,
                  render: (v) => v ? <Text type="danger">{v}</Text> : '-'
                }
              ]}
            />
          </Card>
        </TabPane>

        <TabPane tab="🔑 凭证管理" key="credentials">
          <Card
            title="平台凭证配置"
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenCredentialModal()}>
                添加凭证
              </Button>
            }
          >
            <Table
              dataSource={credentials}
              rowKey="id"
              columns={[
                {
                  title: '平台',
                  dataIndex: 'platform',
                  key: 'platform',
                  width: 120,
                  render: (v) => {
                    const info = PLATFORM_INFO[v]
                    return (
                      <Space>
                        <span>{info?.icon || '🔌'}</span>
                        <Text strong>{info?.name || v}</Text>
                      </Space>
                    )
                  }
                },
                { title: '账号名称', dataIndex: 'account_name', key: 'account_name' },
                { title: '账号ID', dataIndex: 'account_id', key: 'account_id', render: v => v || '-' },
                {
                  title: '验证状态',
                  dataIndex: 'is_verified',
                  key: 'is_verified',
                  width: 100,
                  render: (v) => v ? <Tag color="success">已验证</Tag> : <Tag color="warning">未验证</Tag>
                },
                {
                  title: '自动同步',
                  dataIndex: 'auto_sync_enabled',
                  key: 'auto_sync_enabled',
                  width: 100,
                  render: (v) => v ? <Tag color="blue">已开启</Tag> : <Tag>已关闭</Tag>
                },
                {
                  title: '操作',
                  key: 'actions',
                  width: 200,
                  fixed: 'right',
                  render: (_, record) => (
                    <Space>
                      <Button size="small" icon={<SyncOutlined />} onClick={() => handleVerifyCredential(record.id)}>
                        验证
                      </Button>
                      <Button size="small" icon={<EditOutlined />} onClick={() => handleOpenCredentialModal(record)}>
                        编辑
                      </Button>
                      <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteCredential(record.id)}>
                        删除
                      </Button>
                    </Space>
                  )
                }
              ]}
            />
          </Card>
        </TabPane>

        <TabPane tab="🔄 数据同步" key="sync">
          <Row gutter={16}>
            <Col span={12}>
              <Card title="📥 数据拉取" style={{ marginBottom: 24 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <div>
                    <Text strong>选择平台：</Text>
                    <Select
                      value={selectedPlatform}
                      onChange={setSelectedPlatform}
                      style={{ width: '100%', marginTop: 8 }}
                      size="large"
                    >
                      {Object.entries(connectors || {}).map(([key, info]) => {
                        const p = PLATFORM_INFO[key]
                        return (
                          <Option key={key} value={key}>
                            {p?.icon} {p?.name || key} ({info.source_type})
                          </Option>
                        )
                      })}
                    </Select>
                  </div>

                  <div>
                    <Text strong>报表类型：</Text>
                    <Select
                      value={reportType}
                      onChange={setReportType}
                      style={{ width: '100%', marginTop: 8 }}
                    >
                      {(PLATFORM_INFO[selectedPlatform]?.credentialFields ? ['campaign_daily', 'adset_daily', 'ad_daily'] : ['campaign_daily']).map(rt => (
                        <Option key={rt} value={rt}>{rt}</Option>
                      ))}
                    </Select>
                  </div>

                  <div>
                    <Text strong>日期范围：</Text>
                    <RangePicker
                      value={dateRange}
                      onChange={setDateRange}
                      style={{ width: '100%', marginTop: 8 }}
                      size="large"
                    />
                  </div>

                  <Button
                    type="primary"
                    size="large"
                    icon={<PlayCircleOutlined />}
                    onClick={handlePullData}
                    loading={pullLoading}
                    block
                  >
                    开始拉取数据
                  </Button>

                  <Divider />

                  <Paragraph type="secondary">
                    拉取的数据将自动经过：<br />
                    1️⃣ 平台 API 认证 → 2️⃣ 原始数据保存到 ODS 层 → 3️⃣ 字段标准化映射<br />
                    4️⃣ 幂等性校验 → 5️⃣ 保存到 DWD 事实表
                  </Paragraph>
                </Space>
              </Card>
            </Col>

            <Col span={12}>
              <Card title="📊 DWS 聚合" style={{ marginBottom: 24 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <div>
                    <Text strong>日期范围：</Text>
                    <RangePicker
                      value={dateRange}
                      onChange={setDateRange}
                      style={{ width: '100%', marginTop: 8 }}
                      size="large"
                    />
                  </div>

                  <Button
                    type="primary"
                    size="large"
                    icon={<DatabaseOutlined />}
                    onClick={handleSyncDWS}
                    loading={pullLoading}
                    block
                    style={{ marginTop: 16 }}
                  >
                    重新聚合 DWS 层
                  </Button>

                  <Divider />

                  <Paragraph type="secondary">
                    聚合流程：<br />
                    1️⃣ 删除指定日期范围内的旧聚合数据 → 2️⃣ 关联媒体+MMP数据<br />
                    3️⃣ 计算衍生指标（CTR/CPC/CPM/CPI/ROI等）→ 4️⃣ 保存到 agg_ua_daily
                  </Paragraph>
                </Space>
              </Card>

              <Card title="📋 数据分层说明">
                <Timeline>
                  <Timeline.Item color="blue">
                    <Text strong>ODS 层</Text> - 原始数据<br />
                    <Text type="secondary">保存各平台 API 原始响应 JSON，100% 溯源能力</Text>
                  </Timeline.Item>
                  <Timeline.Item color="green">
                    <Text strong>DWD 层</Text> - 事实表<br />
                    <Text type="secondary">标准化字段、幂等去重后的明细数据</Text>
                  </Timeline.Item>
                  <Timeline.Item color="cyan">
                    <Text strong>DWS 层</Text> - 聚合宽表<br />
                    <Text type="secondary">多维度聚合，ROI360 核心计算层</Text>
                  </Timeline.Item>
                  <Timeline.Item color="purple">
                    <Text strong>ADS 层</Text> - 应用服务<br />
                    <Text type="secondary">Dashboard 缓存、健康度评分、异常预警</Text>
                  </Timeline.Item>
                </Timeline>
              </Card>
            </Col>
          </Row>
        </TabPane>

        <TabPane tab="📝 同步历史" key="history">
          <Card
            title="同步任务历史"
            extra={
              <Space>
                <Select placeholder="按平台过滤" style={{ width: 150 }} allowClear>
                  {Object.keys(connectors || {}).map(key => (
                    <Option key={key} value={key}>{PLATFORM_INFO[key]?.name || key}</Option>
                  ))}
                </Select>
                <Select placeholder="按状态过滤" style={{ width: 120 }} allowClear>
                  <Option value="success">成功</Option>
                  <Option value="failed">失败</Option>
                  <Option value="running">运行中</Option>
                </Select>
              </Space>
            }
          >
            <Table
              dataSource={runs}
              rowKey="id"
              pagination={{ pageSize: 20, showSizeChanger: true }}
              columns={[
                {
                  title: '状态',
                  dataIndex: 'status',
                  key: 'status',
                  width: 100,
                  fixed: 'left',
                  render: (v) => (
                    <Space>
                      {getStatusIcon(v)}
                      <Tag color={getStatusColor(v)}>{v}</Tag>
                    </Space>
                  )
                },
                { title: '平台', dataIndex: 'connector', key: 'connector', width: 100 },
                { title: '数据源类型', dataIndex: 'source_type', key: 'source_type', width: 100 },
                { title: '操作类型', dataIndex: 'operation', key: 'operation', width: 100 },
                { title: '报表类型', dataIndex: 'report_type', key: 'report_type', width: 150 },
                { title: '日期从', dataIndex: 'date_from', key: 'date_from', width: 120 },
                { title: '日期到', dataIndex: 'date_to', key: 'date_to', width: 120 },
                { title: '原始行数', dataIndex: 'raw_row_count', key: 'raw', width: 100 },
                { title: '标准化行数', dataIndex: 'normalized_row_count', key: 'norm', width: 120 },
                {
                  title: '创建时间',
                  dataIndex: 'created_at',
                  key: 'created_at',
                  width: 180,
                  render: (v) => new Date(v).toLocaleString()
                },
                {
                  title: '错误详情',
                  dataIndex: 'error_detail',
                  key: 'error',
                  width: 200,
                  ellipsis: true,
                  render: (v) => v ? <Text type="danger">{v}</Text> : '-'
                }
              ]}
              scroll={{ x: 1400 }}
            />
          </Card>
        </TabPane>
      </Tabs>

      <Modal
        title={editingCredential ? '编辑凭证' : '添加凭证'}
        open={credentialModalVisible}
        onOk={handleSaveCredential}
        onCancel={() => setCredentialModalVisible(false)}
        confirmLoading={credentialLoading}
        width={600}
      >
        <Form form={credentialForm} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select onChange={() => credentialForm.setFieldsValue({})}>
              {Object.entries(PLATFORM_INFO).map(([key, info]) => (
                <Option key={key} value={key}>{info.icon} {info.name}</Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="account_name" label="账号名称" rules={[{ required: true, message: '请输入账号名称' }]}>
            <Input placeholder="例如：Meta 主账号" />
          </Form.Item>

          <Form.Item name="account_id" label="账号 ID">
            <Input placeholder="可选，广告账号/应用 ID" />
          </Form.Item>

          <Divider>API 凭证</Divider>

          {renderCredentialFields()}

          <Divider>同步配置</Divider>

          <Form.Item name="sync_frequency" label="同步频率" initialValue="daily">
            <Select>
              <Option value="hourly">每小时</Option>
              <Option value="daily">每天</Option>
              <Option value="weekly">每周</Option>
            </Select>
          </Form.Item>

          <Form.Item name="auto_sync_enabled" label="自动同步" valuePropName="checked" initialValue={false}>
            <Switch />
          </Form.Item>

          <Form.Item name="notes" label="备注">
            <TextArea rows={3} placeholder="备注信息" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ConnectorManagement
