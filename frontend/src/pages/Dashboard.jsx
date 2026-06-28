import React, { useState, useEffect } from 'react'
import { Card, Row, Col, Statistic, Table, Tag, Space, Progress, Select, DatePicker, Button, Typography, Modal, Descriptions, List, Avatar, message } from 'antd'

const { Text } = Typography
import {
  DollarOutlined,
  RiseOutlined,
  DownOutlined,
  BarChartOutlined,
  ThunderboltOutlined,
  EyeOutlined,
  WarningOutlined,
  InfoCircleOutlined
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as echarts from 'echarts'
import api, { campaignAPI, dataAPI } from '../api'

const { Option } = Select
const { RangePicker } = DatePicker

function Dashboard({ user }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [campaigns, setCampaigns] = useState([])
  const [alerts, setAlerts] = useState([])
  const [currentApp, setCurrentApp] = useState({ id: 1, name: 'Block Blast' })
  const [alertModalVisible, setAlertModalVisible] = useState(false)
  const [currentAlert, setCurrentAlert] = useState(null)

  useEffect(() => {
    loadData()
    initChart()
  }, [])

  const loadData = async () => {
    try {
      const [campaignsData, alertsData] = await Promise.all([
        campaignAPI.list({ app_id: 1 }),
        dataAPI.getAlerts(1)
      ])
      setCampaigns(campaignsData || [])
      setAlerts(alertsData || [])
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
      message.error('Failed to load dashboard data')
      setCampaigns([])
      setAlerts([])
    } finally {
      setLoading(false)
    }
  }

  const initChart = () => {
    setTimeout(() => {
      const chartDom = document.getElementById('roiChart')
      if (chartDom) {
        const myChart = echarts.init(chartDom)
        myChart.setOption({
          title: { text: 'ROI 趋势' },
          tooltip: { trigger: 'axis' },
          legend: { data: ['ROI D3', 'ROI D7', 'ROI D30'] },
          xAxis: {
            type: 'category',
            data: ['6/20', '6/21', '6/22', '6/23', '6/24', '6/25', '6/26']
          },
          yAxis: { type: 'value', min: 0, max: 2 },
          series: [
            { name: 'ROI D3', type: 'line', data: [0.85, 0.92, 0.88, 0.95, 1.02, 0.98, 1.05] },
            { name: 'ROI D7', type: 'line', data: [1.05, 1.12, 1.08, 1.15, 1.22, 1.18, 1.25] },
            { name: 'ROI D30', type: 'line', data: [1.35, 1.42, 1.38, 1.45, 1.52, 1.48, 1.55] },
          ]
        })
      }
    }, 100)
  }

  const getRoiColor = (val) => {
    if (val === null || val === undefined) return '#999'
    if (val >= 1.2) return '#52c41a'
    if (val >= 0.8) return '#faad14'
    return '#ff4d4f'
  }

  const columns = [
    {
      title: 'Campaign 名称',
      dataIndex: 'name',
      key: 'name',
      fixed: 'left',
      width: 220,
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <a onClick={() => navigate(`/campaign/${record.id}`)} style={{ fontWeight: 500 }}>
            {text}
          </a>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {record.country} · {record.platform}
          </Text>
        </Space>
      )
    },
    {
      title: '媒体/DSP',
      dataIndex: 'media',
      key: 'media',
      width: 100,
      render: (val, record) => (
        <Space direction="vertical" size={0}>
          <Tag color="blue">{val}</Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>{record.dsp}</Text>
        </Space>
      )
    },
    {
      title: '类型/目标',
      key: 'type',
      width: 120,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{record.campaign_type}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>目标: {record.objective}</Text>
        </Space>
      )
    },
    {
      title: '出价策略',
      key: 'bid',
      width: 120,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{record.bid_strategy}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>优化: {record.optimization_goal}</Text>
        </Space>
      )
    },
    {
      title: 'ROI D7',
      dataIndex: 'roi',
      key: 'roi',
      width: 80,
      sorter: (a, b) => (Number(a.roi) || 0) - (Number(b.roi) || 0),
      render: (val) => {
        const numVal = Number(val)
        return (
          <span style={{ color: !isNaN(numVal) ? getRoiColor(numVal) : '#999', fontWeight: 'bold', fontSize: 14 }}>
            {!isNaN(numVal) ? `${numVal.toFixed(2)}x` : '-'}
          </span>
        )
      }
    },
    {
      title: '花费 ($)',
      dataIndex: 'spend',
      key: 'spend',
      width: 100,
      sorter: (a, b) => (Number(a.spend) || 0) - (Number(b.spend) || 0),
      render: (val, record) => {
        const numVal = Number(val) || 0
        const budget = Number(record.budget) || 0
        return (
          <Space direction="vertical" size={0}>
            <Text style={{ fontWeight: 500 }}>{numVal > 0 ? numVal.toLocaleString() : '-'}</Text>
            <Progress percent={budget > 0 ? Math.round(numVal / budget * 100) : 0} size="small" />
          </Space>
        )
      }
    },
    {
      title: '预算 ($)',
      dataIndex: 'budget',
      key: 'budget',
      width: 90,
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    {
      title: 'CPI ($)',
      dataIndex: 'cpi',
      key: 'cpi',
      width: 90,
      sorter: (a, b) => (Number(a.cpi) || 0) - (Number(b.cpi) || 0),
      render: (val, record) => {
        const cpiValue = Number(val) || 0
        const targetValue = Number(record.target_cpi) || 0
        return (
          <Space direction="vertical" size={0}>
            <Text style={{ color: cpiValue > targetValue ? '#ff4d4f' : '#52c41a' }}>
              {cpiValue > 0 ? cpiValue.toFixed(2) : '-'}
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              目标: {targetValue > 0 ? targetValue.toFixed(2) : '-'}
            </Text>
          </Space>
        )
      }
    },
    {
      title: '安装量',
      dataIndex: 'installs',
      key: 'installs',
      width: 90,
      sorter: (a, b) => (Number(a.installs) || 0) - (Number(b.installs) || 0),
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    {
      title: 'CTR',
      dataIndex: 'ctr',
      key: 'ctr',
      width: 70,
      render: (val) => {
        const numVal = Number(val)
        return !isNaN(numVal) ? `${numVal}%` : '-'
      }
    },
    {
      title: '健康度',
      dataIndex: 'health',
      key: 'health',
      width: 80,
      render: (val) => {
        const colorMap = { excellent: 'success', good: 'processing', warning: 'warning', danger: 'error', pending: 'default' }
        const labelMap = { excellent: '优秀', good: '良好', warning: '警告', danger: '危险', pending: '待投放' }
        return <Tag color={colorMap[val] || 'default'}>{labelMap[val] || val}</Tag>
      }
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (val) => {
        const statusMap = {
          running: <Tag icon={<ThunderboltOutlined />} color="success">投放中</Tag>,
          paused: <Tag color="warning">已暂停</Tag>,
          draft: <Tag color="default">草稿</Tag>,
          ended: <Tag color="error">已结束</Tag>,
          api_submitted: <Tag color="processing">API提交中</Tag>
        }
        return statusMap[val] || <Tag>{val}</Tag>
      }
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 150,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/campaign/${record.id}`)}>
            详情
          </Button>
          <a onClick={() => navigate(`/intent?q=暂停 ${record.name}`)}>暂停</a>
          <a onClick={() => navigate(`/intent?q=优化 ${record.name}`)}>优化</a>
        </Space>
      )
    }
  ]

  const handleViewAlert = (alert) => {
    setCurrentAlert(alert)
    setAlertModalVisible(true)
  }

  const handleResolveAlert = async (alertId) => {
    try {
      await api.put(`/data/alerts/${alertId}/resolve`)
      setAlerts(prev => prev.filter(a => a.id !== alertId))
      setAlertModalVisible(false)
      message.success('告警已处理')
    } catch (error) {
      console.error('Failed to resolve alert:', error)
      message.error('处理告警失败')
    }
  }

  const alertColumns = [
    {
      title: '告警级别',
      dataIndex: 'severity',
      key: 'severity',
      width: 80,
      render: (v) =>
        <Tag color={v === 'high' ? 'red' : 'orange'}>
          {v === 'high' ? '高危' : '中等'}
        </Tag>
    },
    {
      title: '告警内容',
      dataIndex: 'message',
      key: 'message',
      render: (text, record) => {
        const time = record.detected_at
          ? record.detected_at.includes('T')
            ? record.detected_at.split('T')[1].substring(0, 5)
            : record.detected_at.split(' ')[1] || record.detected_at
          : '';
        return (
          <div style={{ cursor: 'pointer' }} onClick={() => handleViewAlert(record)}>
            <div style={{ fontWeight: 500 }}>{text}</div>
            <div style={{ fontSize: 11, color: '#999' }}>
              检测时间: {time}
            </div>
          </div>
        );
      }
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => handleViewAlert(record)}>
            详情
          </Button>
          <Button type="primary" size="small" onClick={() => handleResolveAlert(record.id)}>
            处理
          </Button>
        </Space>
      )
    }
  ]

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>📊 投放大盘</h2>
        <Space>
          <Select defaultValue={currentApp.id} style={{ width: 200 }} onChange={(v) => setCurrentApp({id: v, name: v})}>
            <Option value={1}>Block Blast</Option>
            <Option value={2}>Mahjong Master</Option>
          </Select>
          <RangePicker />
        </Space>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic 
              title="今日花费" 
              value={33900} 
              precision={0}
              prefix={<DollarOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic 
              title="整体 ROI" 
              value={1.02} 
              precision={2}
              suffix="x"
              prefix={<RiseOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic 
              title="安装量" 
              value={13150} 
              precision={0}
              prefix={<DownOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic 
              title="活跃 Campaign" 
              value={18} 
              prefix={<BarChartOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表 + 告警 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={16}>
          <Card title="ROI 趋势分析">
            <div id="roiChart" style={{ height: 300 }}></div>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="⚠️ 待处理告警" extra={<Button type="link" size="small">查看全部</Button>}>
            <Table
              dataSource={alerts}
              columns={alertColumns}
              pagination={false}
              size="small"
              onRow={(record) => ({
                onClick: () => handleViewAlert(record),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>
        </Col>
      </Row>

      {/* 告警详情弹窗 */}
      <Modal
        title={
          <Space>
            <WarningOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
            <span>告警详情</span>
            {currentAlert?.severity === 'high' && <Tag color="red">高危</Tag>}
            {currentAlert?.severity === 'medium' && <Tag color="orange">中等</Tag>}
          </Space>
        }
        open={alertModalVisible}
        onCancel={() => setAlertModalVisible(false)}
        width={700}
        footer={[
          <Button key="close" onClick={() => setAlertModalVisible(false)}>
            关闭
          </Button>,
          <Button key="resolve" type="primary" onClick={() => currentAlert && handleResolveAlert(currentAlert.id)}>
            标记已处理
          </Button>,
        ]}
      >
        {currentAlert && (
          <div>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="告警内容" span={2}>
                <span style={{ fontWeight: 500, color: '#ff4d4f' }}>{currentAlert.message}</span>
              </Descriptions.Item>
              <Descriptions.Item label="关联 Campaign" span={2}>
                <a onClick={() => navigate(`/campaign/${currentAlert.campaign_id}`)} style={{ cursor: 'pointer' }}>
                  {currentAlert.campaign_name}
                </a>
              </Descriptions.Item>
              <Descriptions.Item label="告警指标">
                {currentAlert.metric}
              </Descriptions.Item>
              <Descriptions.Item label="变化趋势">
                <Tag color={currentAlert.trend === 'up' ? 'red' : 'orange'}>
                  {currentAlert.trend === 'up' ? '↑ 上升' : '↓ 下降'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="当前值">
                <span style={{ color: '#ff4d4f', fontWeight: 500 }}>
                  {currentAlert.metric?.includes('ROI') || currentAlert.metric?.includes('CPI')
                    ? Number(currentAlert.current_value).toFixed(2)
                    : `$${Number(currentAlert.current_value).toLocaleString()}`}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="历史值">
                {currentAlert.metric?.includes('ROI') || currentAlert.metric?.includes('CPI')
                    ? Number(currentAlert.previous_value).toFixed(2)
                    : `$${Number(currentAlert.previous_value).toLocaleString()}`}
              </Descriptions.Item>
              <Descriptions.Item label="告警阈值">
                {Number(currentAlert.threshold).toFixed(2)}
              </Descriptions.Item>
              <Descriptions.Item label="检测时间" span={2}>
                {currentAlert.detected_at?.replace('T', ' ')}
              </Descriptions.Item>
              <Descriptions.Item label="问题描述" span={2}>
                {currentAlert.description}
              </Descriptions.Item>
            </Descriptions>

            <h4 style={{ marginBottom: 12 }}>📊 受影响 Campaign</h4>
            <List
              size="small"
              dataSource={currentAlert.affected_campaigns}
              bordered
              style={{ marginBottom: 16 }}
              renderItem={(camp) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => {
                    navigate(`/campaign/${camp.id}`)
                    setAlertModalVisible(false)
                  }}
                >
                  <List.Item.Meta
                    avatar={<Avatar size="small" style={{ background: '#1890ff' }}>{camp.name.charAt(0)}</Avatar>}
                    title={<span style={{ fontWeight: 500 }}>{camp.name}</span>}
                    description={
                      <div style={{ fontSize: 12, color: '#666' }}>
                        <Space split="|">
                          <span>花费: ${Number(camp.spend).toLocaleString()}</span>
                          {camp.roi !== undefined && camp.roi !== null && <span>ROI: {Number(camp.roi).toFixed(2)}</span>}
                          {camp.cpi !== undefined && camp.cpi !== null && <span>CPI: ${Number(camp.cpi).toFixed(2)}</span>}
                        </Space>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />

            <h4 style={{ marginBottom: 12 }}>💡 建议操作</h4>
            <List
              size="small"
              dataSource={currentAlert.suggested_actions}
              bordered
              renderItem={(action, index) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={<Avatar size="small" style={{ background: '#52c41a' }}>{index + 1}</Avatar>}
                    description={action}
                  />
                </List.Item>
              )}
            />
          </div>
        )}
      </Modal>

      {/* Campaign 列表 */}
      <Card
        title="Campaign 列表"
        extra={
          <Space>
            <Select placeholder="按媒体筛选" style={{ width: 120 }} allowClear>
              <Option value="Meta">Meta</Option>
              <Option value="Google">Google</Option>
              <Option value="TikTok">TikTok</Option>
            </Select>
            <Select placeholder="按状态筛选" style={{ width: 120 }} allowClear>
              <Option value="running">投放中</Option>
              <Option value="paused">已暂停</Option>
            </Select>
          </Space>
        }
      >
        <Table
          dataSource={campaigns}
          columns={columns}
          rowKey="id"
          scroll={{ x: 1600 }}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          size="small"
        />
      </Card>
    </div>
  )
}

export default Dashboard
