import React, { useState, useEffect } from 'react'
import {
  Card,
  Table,
  Tag,
  Space,
  Button,
  Breadcrumb,
  Typography,
  Statistic,
  Row,
  Col,
  Progress,
  Tabs,
  List,
  Descriptions,
  Spin
} from 'antd'
import {
  ArrowLeftOutlined,
  RiseOutlined,
  DollarOutlined,
  DownOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import * as echarts from 'echarts'
import { campaignAPI } from '../api'

const { Title, Text } = Typography
const { TabPane } = Tabs


function CampaignDetail() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [campaign, setCampaign] = useState(null)
  const [loading, setLoading] = useState(true)
  const [adGroups, setAdGroups] = useState([])
  const [selectedAdGroup, setSelectedAdGroup] = useState(null)
  const [ads, setAds] = useState([])
  const [activeTab, setActiveTab] = useState('overview')

  useEffect(() => {
    loadCampaignData()
    initChart()
  }, [id])

  const loadCampaignData = async () => {
    setLoading(true)
    try {
      const campaignId = parseInt(id, 10)
      const cam = await campaignAPI.get(campaignId)
      if (cam) {
        setCampaign(cam)
        // 使用嵌套的 ad_groups 数据（API已返回完整嵌套数据
        const groups = cam.ad_groups || []
        setAdGroups(groups)
        if (groups.length > 0) {
          setSelectedAdGroup(groups[0])
          setAds(groups[0].ads || [])
        }
      }
    } catch (error) {
      console.error('Failed to load campaign data:', error)
    } finally {
      setLoading(false)
    }
  }

  const initChart = () => {
    setTimeout(() => {
      const chartDom = document.getElementById('trendChart')
      if (chartDom) {
        const myChart = echarts.init(chartDom)
        myChart.setOption({
          title: { text: '近7天花费&ROI趋势' },
          tooltip: { trigger: 'axis' },
          legend: { data: ['日花费($)', 'ROI'] },
          xAxis: { type: 'category', data: ['6/21', '6/22', '6/23', '6/24', '6/25', '6/26', '6/27'] },
          yAxis: [
            { type: 'value', name: '花费($)' },
            { type: 'value', name: 'ROI', min: 0, max: 2 }
          ],
          series: [
            { name: '日花费($)', type: 'bar', data: [1650, 1720, 1580, 1890, 1920, 1850, 1890] },
            { name: 'ROI', type: 'line', yAxisIndex: 1, data: [1.18, 1.22, 1.25, 1.23, 1.28, 1.26, 1.25] }
          ]
        })
      }
    }, 100)
  }

  const handleAdGroupClick = (adGroup) => {
    setSelectedAdGroup(adGroup)
    setAds(adGroup.ads || [])
    setActiveTab('ads')
  }

  if (loading) {
    return <div style={{ padding: 24, textAlign: 'center' }}><Spin tip="加载中..." /></div>
  }

  if (!campaign) {
    return <div style={{ padding: 24 }}>Campaign不存在</div>
  }

  const getStatusColor = (roi) => {
    const numRoi = Number(roi)
    if (isNaN(numRoi)) return 'default'
    if (numRoi >= 1.2) return 'success'
    if (numRoi >= 0.8) return 'warning'
    return 'error'
  }

  const getStatusTag = (status) => {
    const colorMap = { running: 'green', warning: 'orange', danger: 'red', paused: 'orange', draft: 'default', ended: 'red' }
    const labelMap = { running: '投放中', warning: '需关注', danger: '风险', paused: '已暂停', draft: '草稿', ended: '已结束' }
    return <Tag color={colorMap[status]}>{labelMap[status] || status}</Tag>
  }

  const adGroupColumns = [
    {
      title: 'Ad Group 名称', dataIndex: 'name', key: 'name', width: 220, fixed: 'left',
      render: (text, record) => (
        <a onClick={() => handleAdGroupClick(record)} style={{ fontWeight: selectedAdGroup?.id === record.id ? 'bold' : 'normal' }}>
          {text}
        </a>
      )
    },
    { title: 'ROI', dataIndex: 'roi', key: 'roi', width: 80, sorter: (a, b) => (Number(a.roi) || 0) - (Number(b.roi) || 0),
      render: (v) => {
        const numVal = Number(v)
        return !isNaN(numVal)
          ? <span style={{ color: getStatusColor(v), fontWeight: 'bold' }}>{numVal.toFixed(2)}</span>
          : <span style={{ color: '#999' }}>-</span>
      }
    },
    { title: '花费 ($)', dataIndex: 'spend', key: 'spend', width: 100, sorter: (a, b) => Number(a.spend) - Number(b.spend),
      render: (v) => {
        const numVal = Number(v)
        return !isNaN(numVal) ? numVal.toLocaleString() : '-'
      }
    },
    { title: 'CPI ($)', dataIndex: 'cpi', key: 'cpi', width: 90,
      render: (v) => {
        const numVal = Number(v)
        return numVal > 0 ? numVal.toFixed(2) : '-'
      }
    },
    { title: '安装量', dataIndex: 'installs', key: 'installs', width: 90,
      render: (v) => {
        const numVal = Number(v)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    { title: '广告数', dataIndex: 'ad_count', key: 'ad_count', width: 80,
      render: (_, record) => record.ads?.length || 0
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v) => getStatusTag(v) },
    {
      title: '操作', key: 'action', width: 120, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => handleAdGroupClick(record)}>
            查看广告
          </Button>
        </Space>
      )
    }
  ]

  const adColumns = [
    { title: '广告名称', dataIndex: 'name', key: 'name', width: 200 },
    { title: 'ROI', dataIndex: 'roi', key: 'roi', width: 80, sorter: (a, b) => (Number(a.roi) || 0) - (Number(b.roi) || 0),
      render: (v) => {
        const numVal = Number(v)
        return !isNaN(numVal)
          ? <span style={{ color: getStatusColor(numVal), fontWeight: 'bold' }}>{numVal.toFixed(2)}</span>
          : <span style={{ color: '#999' }}>-</span>
      }
    },
    { title: '花费 ($)', dataIndex: 'spend', key: 'spend', width: 100,
      render: (v) => {
        const numVal = Number(v)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    { title: '点击量', dataIndex: 'clicks', key: 'clicks', width: 90,
      render: (v) => {
        const numVal = Number(v)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    { title: 'CTR', dataIndex: 'ctr', key: 'ctr', width: 80,
      render: (v) => {
        const numVal = Number(v)
        return !isNaN(numVal) ? `${numVal.toFixed(2)}%` : '-'
      }
    },
    { title: '曝光量', dataIndex: 'impressions', key: 'impressions', width: 110,
      render: (v) => {
        const numVal = Number(v)
        return numVal > 0 ? numVal.toLocaleString() : '-'
      }
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v) => getStatusTag(v) },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/dashboard')}>
          返回列表
        </Button>
        <Breadcrumb>
          <Breadcrumb.Item>投放大盘</Breadcrumb.Item>
          <Breadcrumb.Item>Campaign 详情</Breadcrumb.Item>
          <Breadcrumb.Item>{campaign.name}</Breadcrumb.Item>
        </Breadcrumb>
      </Space>

      {/* Campaign 概览卡片 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={16}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Title level={3} style={{ margin: 0 }}>
                {campaign.name} {getStatusTag(campaign.status)}
              </Title>
              <Space wrap>
                <Tag color="blue">{campaign.media}</Tag>
                <Tag>{campaign.dsp}</Tag>
                <Tag color="purple">{campaign.campaign_type}</Tag>
                <Tag color="green">目标: {campaign.objective}</Tag>
              </Space>
              <Descriptions column={6} size="small" style={{ marginTop: 8 }}>
                <Descriptions.Item label="地区">{campaign.country}</Descriptions.Item>
                <Descriptions.Item label="平台">{campaign.platform}</Descriptions.Item>
                <Descriptions.Item label="出价策略">{campaign.bid_strategy}</Descriptions.Item>
                <Descriptions.Item label="优化目标">{campaign.optimization_goal}</Descriptions.Item>
                <Descriptions.Item label="开始日期">{campaign.start_date}</Descriptions.Item>
                <Descriptions.Item label="更新时间">{campaign.last_update}</Descriptions.Item>
              </Descriptions>
            </Space>
          </Col>
          <Col span={8}>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title="ROI"
                  value={Number(campaign.roi)}
                  precision={2}
                  valueStyle={{ color: getStatusColor(campaign.roi), fontSize: 24 }}
                  prefix={<RiseOutlined />}
                  formatter={(v) => !isNaN(v) ? v.toFixed(2) : '-'}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="花费进度"
                  value={Number(campaign.budget) > 0 ? Math.round(Number(campaign.spend) / Number(campaign.budget) * 100) : 0}
                  precision={0}
                  suffix="%"
                  prefix={<DollarOutlined />}
                />
                <Progress percent={Number(campaign.budget) > 0 ? Math.round(Number(campaign.spend || 0) / Number(campaign.budget) * 100) : 0} size="small" />
              </Col>
            </Row>
          </Col>
        </Row>
        <Row gutter={16} style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
          <Col span={3}>
            <Statistic title="总预算" value={Number(campaign.budget)} precision={0} prefix="$" formatter={(v) => !isNaN(v) ? v.toLocaleString() : '-'} />
          </Col>
          <Col span={3}>
            <Statistic title="已花费" value={Number(campaign.spend)} precision={0} prefix="$" valueStyle={{ color: '#1890ff' }} formatter={(v) => !isNaN(v) ? v.toLocaleString() : '-'} />
          </Col>
          <Col span={3}>
            <Statistic
              title="CPI"
              value={Number(campaign.cpi)}
              precision={2}
              prefix="$"
              valueStyle={{ color: (Number(campaign.cpi) || 0) > Number(campaign.target_cpi) ? '#ff4d4f' : '#52c41a' }}
              formatter={(v) => v > 0 ? v.toFixed(2) : '-'}
            />
          </Col>
          <Col span={3}>
            <Statistic title="目标 CPI" value={Number(campaign.target_cpi)} precision={2} prefix="$" formatter={(v) => !isNaN(v) ? v.toFixed(2) : '-'} />
          </Col>
          <Col span={3}>
            <Statistic title="安装量" value={Number(campaign.installs)} precision={0} formatter={(v) => !isNaN(v) ? v.toLocaleString() : '-'} />
          </Col>
          <Col span={3}>
            <Statistic title="曝光量" value={Number(campaign.impressions)} precision={0} formatter={(v) => !isNaN(v) ? v.toLocaleString() : '-'} />
          </Col>
          <Col span={3}>
            <Statistic title="点击量" value={Number(campaign.clicks)} precision={0} formatter={(v) => !isNaN(v) ? v.toLocaleString() : '-'} />
          </Col>
          <Col span={3}>
            <Statistic title="CTR" value={Number(campaign.ctr)} suffix="%" formatter={(v) => !isNaN(v) ? v.toFixed(2) : '-'} />
          </Col>
        </Row>
      </Card>

      {/* Tabs */}
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="📊 概览" key="overview">
          <Card title="趋势分析" style={{ marginBottom: 16 }}>
            <div id="trendChart" style={{ height: 300 }}></div>
          </Card>
          
          <Card title="Ad Group 列表" extra={<span>共 {adGroups.length} 个 Ad Group</span>}>
            <Table
              dataSource={adGroups}
              columns={adGroupColumns}
              rowKey="id"
              scroll={{ x: 1100 }}
              pagination={false}
              size="small"
            />
          </Card>
        </TabPane>

        <TabPane tab="🎯 Ad Group 详情" key="adgroup">
          {selectedAdGroup ? (
            <div>
              <Card title={`Ad Group: ${selectedAdGroup.name}`} style={{ marginBottom: 16 }}>
                <Descriptions column={4}>
                  <Descriptions.Item label="ROI">
                    {Number(selectedAdGroup.roi) ? Number(selectedAdGroup.roi).toFixed(2) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="花费">
                    ${Number(selectedAdGroup.spend) > 0 ? Number(selectedAdGroup.spend).toLocaleString() : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="CPI">
                    ${Number(selectedAdGroup.cpi) > 0 ? Number(selectedAdGroup.cpi).toFixed(2) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="安装量">
                    {Number(selectedAdGroup.installs) > 0 ? Number(selectedAdGroup.installs).toLocaleString() : '-'}
                  </Descriptions.Item>
                </Descriptions>
              </Card>

              <Card title="Ad 列表" extra={<span>共 {ads.length} 个广告</span>}>
                <Table
                  dataSource={ads}
                  columns={adColumns}
                  rowKey="id"
                  scroll={{ x: 1200 }}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  size="small"
                />
              </Card>
            </div>
          ) : (
            <Card><p style={{ textAlign: 'center', color: '#999' }}>该 Campaign 暂无 Ad Group</p></Card>
          )}
        </TabPane>

        <TabPane tab="📝 广告创意" key="ads">
          {selectedAdGroup && ads.length > 0 ? (
            <List
              grid={{ gutter: 16, column: 3 }}
              dataSource={ads}
              renderItem={ad => {
                const adRoi = Number(ad.roi)
                const adSpend = Number(ad.spend)
                const adClicks = Number(ad.clicks)
                const adImpressions = Number(ad.impressions)
                return (
                  <List.Item>
                    <Card
                      hoverable
                      title={ad.name}
                      extra={
                        <Tag color={getStatusColor(adRoi)}>
                          ROI: {adRoi ? adRoi.toFixed(2) : '-'}
                        </Tag>
                      }
                    >
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <div>花费: ${adSpend > 0 ? adSpend.toLocaleString() : '-'}</div>
                        <div>点击: {adClicks > 0 ? adClicks.toLocaleString() : '-'}</div>
                        <div>CTR: {Number(ad.ctr) ? Number(ad.ctr).toFixed(2) : '-'}</div>
                        <div>曝光: {adImpressions > 0 ? adImpressions.toLocaleString() : '-'}</div>
                        {adRoi ? (
                          <Progress percent={Math.round(adRoi * 50)} status={adRoi >= 1.2 ? 'success' : 'exception'} />
                        ) : <Progress percent={0} status="normal" />}
                        <Space>
                          <Button size="small" type="primary">优化素材</Button>
                          <Button size="small" danger>暂停广告</Button>
                        </Space>
                      </Space>
                    </Card>
                  </List.Item>
                )
              }}
            />
          ) : selectedAdGroup ? (
            <Card><p style={{ textAlign: 'center', color: '#999' }}>该 Ad Group 暂无广告创意</p></Card>
          ) : (
            <Card><p style={{ textAlign: 'center', color: '#999' }}>请先选择一个 Ad Group</p></Card>
          )}
        </TabPane>

        <TabPane tab="⚙️ 设置" key="settings">
          <Card>
            <Descriptions column={2} title="Campaign 设置">
              <Descriptions.Item label="Campaign 名称">{campaign.name}</Descriptions.Item>
              <Descriptions.Item label="投放状态">{campaign.status === 'running' ? '投放中' : campaign.status || '-'}</Descriptions.Item>
              <Descriptions.Item label="媒体平台">{campaign.media || '-'}</Descriptions.Item>
              <Descriptions.Item label="DSP">{campaign.dsp || '-'}</Descriptions.Item>
              <Descriptions.Item label="活动类型">{campaign.campaign_type || '-'}</Descriptions.Item>
              <Descriptions.Item label="优化目标">{campaign.objective || '-'}</Descriptions.Item>
              <Descriptions.Item label="出价策略">{campaign.bid_strategy || '-'}</Descriptions.Item>
              <Descriptions.Item label="优化事件">{campaign.optimization_goal || '-'}</Descriptions.Item>
              <Descriptions.Item label="日预算">${Number(campaign.daily_budget) ? Number(campaign.daily_budget).toLocaleString() : '-'}</Descriptions.Item>
              <Descriptions.Item label="总预算">${Number(campaign.budget) ? Number(campaign.budget).toLocaleString() : '-'}</Descriptions.Item>
              <Descriptions.Item label="目标 CPI">${Number(campaign.target_cpi) ? Number(campaign.target_cpi).toFixed(2) : '-'}</Descriptions.Item>
              <Descriptions.Item label="投放地区">{campaign.country || '-'}</Descriptions.Item>
              <Descriptions.Item label="平台">{campaign.platform || '-'}</Descriptions.Item>
              <Descriptions.Item label="开始日期">{campaign.start_date || '-'}</Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 24 }}>
              <Space>
                <Button type="primary">保存修改</Button>
                <Button danger>暂停 Campaign</Button>
                <Button>重置设置</Button>
              </Space>
            </div>
          </Card>
        </TabPane>
      </Tabs>
    </div>
  )
}

export default CampaignDetail
