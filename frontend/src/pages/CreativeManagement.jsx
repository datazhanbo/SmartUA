import React, { useState, useEffect } from 'react'
import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Space,
  Button,
  Select,
  Input,
  DatePicker,
  Modal,
  Descriptions,
  List,
  Avatar,
  Progress,
  Tabs,
  Image,
  Badge,
  Tooltip,
  Typography,
  Divider
} from 'antd'

const { Text, Paragraph } = Typography
const { TabPane } = Tabs
const { Option } = Select
const { RangePicker } = DatePicker
const { Search } = Input

import {
  VideoCameraOutlined,
  FileImageOutlined,
  AppstoreOutlined,
  EyeOutlined,
  BarChartOutlined,
  RiseOutlined,
  DollarOutlined,
  UserOutlined,
  TagOutlined,
  LinkOutlined,
  DownloadOutlined
} from '@ant-design/icons'
import { campaignAPI } from '../api'

function CreativeManagement({ user }) {
  const [loading, setLoading] = useState(true)
  const [creatives, setCreatives] = useState([])
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [currentCreative, setCurrentCreative] = useState(null)
  const [selectedTab, setSelectedTab] = useState('all')
  const [searchText, setSearchText] = useState('')

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const data = await campaignAPI.getCreatives({ app_id: 1 })
      setCreatives(data || [])
    } catch (error) {
      console.error('Failed to load creatives:', error)
      setCreatives([])
    } finally {
      setLoading(false)
    }
  }

  const getTypeIcon = (type) => {
    const iconMap = {
      video: <VideoCameraOutlined style={{ color: '#1890ff' }} />,
      image: <FileImageOutlined style={{ color: '#52c41a' }} />,
      playable: <AppstoreOutlined style={{ color: '#722ed1' }} />,
      carousel: <FileImageOutlined style={{ color: '#fa8c16' }} />
    }
    return iconMap[type] || <FileImageOutlined />
  }

  const getTypeLabel = (type) => {
    const labelMap = {
      video: '视频',
      image: '图片',
      playable: '试玩',
      carousel: '轮播'
    }
    return labelMap[type] || type
  }

  const getTrendColor = (trend) => {
    const colorMap = { up: '#52c41a', down: '#ff4d4f', stable: '#faad14' }
    return colorMap[trend] || '#999'
  }

  const getPerformanceColor = (score) => {
    if (!score && score !== 0) return '#d9d9d9'
    if (score >= 80) return '#52c41a'
    if (score >= 60) return '#faad14'
    return '#ff4d4f'
  }

  const safeFormat = (val, formatter, fallback = '-') => {
    if (val === null || val === undefined) return fallback
    const numVal = Number(val)
    return isNaN(numVal) ? fallback : formatter(numVal)
  }

  const handleViewDetail = (creative) => {
    setCurrentCreative(creative)
    setDetailModalVisible(true)
  }

  const filteredCreatives = creatives.filter(c => {
    const matchType = selectedTab === 'all' || c.type === selectedTab
    const matchSearch = !searchText ||
      c.name.toLowerCase().includes(searchText.toLowerCase()) ||
      c.tags.some(t => t.toLowerCase().includes(searchText.toLowerCase())) ||
      c.designer.includes(searchText)
    return matchType && matchSearch
  })

  const columns = [
    {
      title: '素材预览',
      dataIndex: 'thumbnail',
      key: 'thumbnail',
      width: 120,
      render: (_, record) => (
        <div style={{ cursor: 'pointer' }} onClick={() => handleViewDetail(record)}>
          <Image
            width={80}
            height={45}
            src={record.thumbnail_url}
            preview={false}
            style={{ borderRadius: 4, objectFit: 'cover' }}
          />
          <div style={{ fontSize: 10, color: '#999', marginTop: 2 }}>
            {getTypeIcon(record.type)} {getTypeLabel(record.type)}
          </div>
        </div>
      )
    },
    {
      title: '素材名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <a onClick={() => handleViewDetail(record)} style={{ fontWeight: 500 }}>
            {text}
          </a>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {record.resolution} · {(Number(record.file_size) / 1024 / 1024).toFixed(1)}MB
          </Text>
        </Space>
      )
    },
    {
      title: '设计师',
      dataIndex: 'designer',
      key: 'designer',
      width: 100,
      render: (text) => (
        <Space>
          <Avatar size="small" icon={<UserOutlined />} />
          {text}
        </Space>
      )
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 200,
      render: (tags) => (
        <div>
          {tags.slice(0, 3).map((tag, idx) => (
            <Tag key={idx} size="small" style={{ marginBottom: 4 }}>
              {tag}
            </Tag>
          ))}
          {tags.length > 3 && <Tag size="small">+{tags.length - 3}</Tag>}
        </div>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (val) => {
        const statusMap = {
          active: <Tag color="green">投放中</Tag>,
          paused: <Tag color="default">已暂停</Tag>,
          testing: <Tag color="blue">测试中</Tag>,
          archived: <Tag color="gray">已归档</Tag>
        }
        return statusMap[val] || val
      }
    },
    {
      title: '花费 ($)',
      dataIndex: 'spend',
      key: 'spend',
      width: 90,
      sorter: (a, b) => (Number(a.spend) || 0) - (Number(b.spend) || 0),
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0 ? <span style={{ fontWeight: 500 }}>{numVal.toLocaleString()}</span> : '-'
      }
    },
    {
      title: '展示',
      dataIndex: 'impressions',
      key: 'impressions',
      width: 90,
      sorter: (a, b) => (Number(a.impressions) || 0) - (Number(b.impressions) || 0),
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0 ? (numVal / 1000).toFixed(1) + 'k' : '-'
      }
    },
    {
      title: '点击',
      dataIndex: 'clicks',
      key: 'clicks',
      width: 80,
      sorter: (a, b) => (Number(a.clicks) || 0) - (Number(b.clicks) || 0),
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0 ? (numVal / 1000).toFixed(1) + 'k' : '-'
      }
    },
    {
      title: 'CTR',
      dataIndex: 'ctr',
      key: 'ctr',
      width: 70,
      sorter: (a, b) => (Number(a.ctr) || 0) - (Number(b.ctr) || 0),
      render: (val) => {
        const numVal = Number(val)
        return !isNaN(numVal)
          ? <span style={{ color: numVal > 2.5 ? '#52c41a' : '#faad14' }}>{numVal.toFixed(2)}%</span>
          : '-'
      }
    },
    {
      title: '安装',
      dataIndex: 'installs',
      key: 'installs',
      width: 70,
      sorter: (a, b) => (Number(a.installs) || 0) - (Number(b.installs) || 0),
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    {
      title: 'CPI ($)',
      dataIndex: 'cpi',
      key: 'cpi',
      width: 70,
      sorter: (a, b) => (Number(a.cpi) || 0) - (Number(b.cpi) || 0),
      render: (val) => {
        const numVal = Number(val)
        return numVal > 0
          ? <span style={{ color: numVal > 2.8 ? '#ff4d4f' : '#52c41a' }}>{numVal.toFixed(2)}</span>
          : '-'
      }
    },
    {
      title: 'ROI',
      dataIndex: 'roi',
      key: 'roi',
      width: 70,
      sorter: (a, b) => (Number(a.roi) || 0) - (Number(b.roi) || 0),
      render: (val) => {
        const numVal = Number(val)
        return !isNaN(numVal) ? (
          <span style={{ color: numVal >= 1.0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
            {numVal.toFixed(2)}x
          </span>
        ) : <span style={{ color: '#999' }}>-</span>
      }
    },
    {
      title: '表现分',
      dataIndex: 'performance_score',
      key: 'performance_score',
      width: 100,
      sorter: (a, b) => (a.performance_score || 0) - (b.performance_score || 0),
      render: (val) => val !== null && val !== undefined ? (
        <Progress
          percent={val}
          size="small"
          strokeColor={getPerformanceColor(val)}
          format={(percent) => <span style={{ fontSize: 11 }}>{percent}</span>}
        />
      ) : '-'
    },
    {
      title: '格式',
      dataIndex: 'format',
      key: 'format',
      width: 80,
      render: (val) => <Tag color="purple">{val?.toUpperCase()}</Tag>
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 120,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(record)}>
            详情
          </Button>
          <Button type="link" size="small" icon={<DownloadOutlined />}>
            下载
          </Button>
        </Space>
      )
    }
  ]

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>🎬 素材管理</h2>
        <Space>
          <Button type="primary" icon={<DownloadOutlined />}>
            上传素材
          </Button>
          <RangePicker />
        </Space>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="素材总数"
              value={creatives.length}
              prefix={<VideoCameraOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总花费"
              value={creatives.reduce((sum, c) => sum + (Number(c.spend) || 0), 0)}
              precision={0}
              prefix={<DollarOutlined />}
              valueStyle={{ color: '#faad14' }}
              formatter={(v) => v.toLocaleString()}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均 ROI"
              value={creatives.length > 0
                ? (creatives.reduce((sum, c) => sum + (Number(c.roi) || 0), 0) / creatives.length).toFixed(2)
                : 0}
              suffix="x"
              prefix={<RiseOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总安装量"
              value={creatives.reduce((sum, c) => sum + (Number(c.installs) || 0), 0)}
              prefix={<BarChartOutlined />}
              formatter={(v) => v.toLocaleString()}
            />
          </Card>
        </Col>
      </Row>

      {/* 素材列表 */}
      <Card
        title={
          <Tabs activeKey={selectedTab} onChange={setSelectedTab} size="small">
            <TabPane tab="全部" key="all" />
            <TabPane tab="视频" key="video" />
            <TabPane tab="图片" key="image" />
            <TabPane tab="试玩" key="playable" />
            <TabPane tab="轮播" key="carousel" />
          </Tabs>
        }
        extra={
          <Space>
            <Search
              placeholder="搜索素材名称/标签/设计师"
              style={{ width: 250 }}
              allowClear
              onSearch={setSearchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
            <Select placeholder="按设计师筛选" style={{ width: 120 }} allowClear>
              <Option value="张三">张三</Option>
              <Option value="李四">李四</Option>
              <Option value="王五">王五</Option>
              <Option value="赵六">赵六</Option>
            </Select>
            <Select placeholder="按状态筛选" style={{ width: 100 }} allowClear>
              <Option value="active">投放中</Option>
              <Option value="paused">已暂停</Option>
              <Option value="testing">测试中</Option>
            </Select>
          </Space>
        }
      >
        <Table
          dataSource={filteredCreatives}
          columns={columns}
          rowKey="id"
          scroll={{ x: 2000 }}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          size="small"
          loading={loading}
          onRow={(record) => ({
            onClick: () => handleViewDetail(record),
            style: { cursor: 'pointer' },
          })}
        />
      </Card>

      {/* 素材详情弹窗 */}
      <Modal
        title={
          <Space>
            {currentCreative && getTypeIcon(currentCreative.type)}
            <span>素材详情</span>
            {currentCreative && (
              <Tag color={
                currentCreative.status === 'active' ? 'green' :
                currentCreative.status === 'testing' ? 'blue' : 'default'
              }>
                {currentCreative.status === 'active' ? '投放中' :
                 currentCreative.status === 'testing' ? '测试中' : '已暂停'}
              </Tag>
            )}
          </Space>
        }
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        width={900}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            关闭
          </Button>,
          <Button key="download" icon={<DownloadOutlined />}>
            下载素材
          </Button>,
        ]}
      >
        {currentCreative && (
          <div>
            <Row gutter={24}>
              <Col span={8}>
                <Card
                  cover={
                    <Image
                      src={currentCreative.thumbnail_url}
                      style={{ height: 200, objectFit: 'cover' }}
                    />
                  }
                >
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="素材名称">
                      {currentCreative.name}
                    </Descriptions.Item>
                    <Descriptions.Item label="素材类型">
                      <Tag icon={getTypeIcon(currentCreative.type)}>
                        {getTypeLabel(currentCreative.type)}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="格式">
                      {currentCreative.format?.toUpperCase()}
                    </Descriptions.Item>
                    <Descriptions.Item label="分辨率">
                      {currentCreative.resolution || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="文件大小">
                      {(Number(currentCreative.file_size) / 1024 / 1024).toFixed(1)}MB
                    </Descriptions.Item>
                    <Descriptions.Item label="时长">
                      {currentCreative.duration ? currentCreative.duration + 's' : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="设计师">
                      <Space>
                        <Avatar size="small" icon={<UserOutlined />} />
                        {currentCreative.designer}
                      </Space>
                    </Descriptions.Item>
                    <Descriptions.Item label="创建时间">
                      {currentCreative.created_at?.split('T')[0] || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="最后使用">
                      {currentCreative.last_used_at?.split('T')[0] || '-'}
                    </Descriptions.Item>
                  </Descriptions>

                  <Divider style={{ margin: '12px 0' }} />

                  <div>
                    <Text strong style={{ marginBottom: 8, display: 'block' }}>
                      <TagOutlined /> 标签
                    </Text>
                    <div>
                      {currentCreative.tags.map((tag, idx) => (
                        <Tag key={idx}>{tag}</Tag>
                      ))}
                    </div>
                  </div>
                </Card>
              </Col>

              <Col span={16}>
                {/* 效果指标 */}
                <Card title="📊 效果指标" size="small" style={{ marginBottom: 16 }}>
                  <Row gutter={16}>
                    <Col span={6}>
                      <Statistic
                        title="花费 ($)"
                        value={currentCreative.spend}
                        precision={0}
                        valueStyle={{ fontSize: 18 }}
                        formatter={(v) => safeFormat(v, x => x.toLocaleString(), '-')}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="展示"
                        value={currentCreative.impressions}
                        formatter={(v) => safeFormat(v, x => (x / 1000000).toFixed(2) + 'M', '-')}
                        valueStyle={{ fontSize: 18 }}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="点击"
                        value={currentCreative.clicks}
                        formatter={(v) => safeFormat(v, x => (x / 1000).toFixed(1) + 'k', '-')}
                        valueStyle={{ fontSize: 18 }}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="CTR"
                        value={currentCreative.ctr}
                        suffix="%"
                        valueStyle={{ fontSize: 18, color: (currentCreative.ctr || 0) > 2.5 ? '#52c41a' : '#faad14' }}
                        formatter={(v) => safeFormat(v, x => x.toFixed(2), '-')}
                      />
                    </Col>
                  </Row>
                  <Row gutter={16} style={{ marginTop: 16 }}>
                    <Col span={6}>
                      <Statistic
                        title="安装"
                        value={currentCreative.installs}
                        valueStyle={{ fontSize: 18 }}
                        formatter={(v) => safeFormat(v, x => x.toLocaleString(), '-')}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="CPI ($)"
                        value={currentCreative.cpi}
                        precision={2}
                        valueStyle={{ fontSize: 18, color: (currentCreative.cpi || 0) > 2.8 ? '#ff4d4f' : '#52c41a' }}
                        formatter={(v) => safeFormat(v, x => x.toFixed(2), '-')}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="转化率"
                        value={currentCreative.conversion_rate}
                        suffix="%"
                        valueStyle={{ fontSize: 18 }}
                        formatter={(v) => safeFormat(v, x => x.toFixed(1), '-')}
                      />
                    </Col>
                    <Col span={6}>
                      <Statistic
                        title="ROI"
                        value={currentCreative.roi}
                        suffix="x"
                        valueStyle={{ fontSize: 18, color: (currentCreative.roi || 0) >= 1.0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}
                        formatter={(v) => safeFormat(v, x => x.toFixed(2), '-')}
                      />
                    </Col>
                  </Row>

                  <div style={{ marginTop: 16, padding: '12px', background: '#f9f9f9', borderRadius: 4 }}>
                    <Space>
                      <Text strong>综合表现分：</Text>
                      {currentCreative.performance_score !== null && currentCreative.performance_score !== undefined ? (
                        <Progress
                          percent={currentCreative.performance_score}
                          size="small"
                          style={{ width: 200 }}
                          strokeColor={getPerformanceColor(currentCreative.performance_score)}
                        />
                      ) : '-'}

                      <Badge
                        count={currentCreative.trend === 'up' ? '↑ 上升' : currentCreative.trend === 'down' ? '↓ 下降' : '→ 稳定'}
                        style={{ backgroundColor: getTrendColor(currentCreative.trend) }}
                      />
                    </Space>
                  </div>
                </Card>

              </Col>
            </Row>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default CreativeManagement
