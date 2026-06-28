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
  Collapse,
  Descriptions,
  Badge,
  Progress,
  Select,
  Pagination,
  Alert,
  Tooltip,
  Empty,
  Spin
} from 'antd'
import {
  DatabaseOutlined,
  TableOutlined,
  ApiOutlined,
  SafetyOutlined,
  RocketOutlined,
  BarChartOutlined,
  InfoCircleOutlined,
  EyeOutlined
} from '@ant-design/icons'
import axios from 'axios'

const { Title, Text, Paragraph } = Typography
const { TabPane } = Tabs
const { Panel } = Collapse
const { Option } = Select

// 数据层颜色映射
const LAYER_COLORS = {
  '系统管理': '#1890ff',
  'ODS层(原始数据)': '#faad14',
  'DWD层(明细数据)': '#52c41a',
  'DWS层(聚合数据)': '#13c2c2',
  'ADS层(应用服务)': '#722ed1',
  '意图引擎': '#eb2f96',
  '其他': '#8c8c8c'
}

// 图标映射
const LAYER_ICONS = {
  '系统管理': <SafetyOutlined />,
  'ODS层(原始数据)': <DatabaseOutlined />,
  'DWD层(明细数据)': <TableOutlined />,
  'DWS层(聚合数据)': <BarChartOutlined />,
  'ADS层(应用服务)': <ApiOutlined />,
  '意图引擎': <RocketOutlined />,
  '其他': <InfoCircleOutlined />
}

function DataManagement() {
  const [loading, setLoading] = useState(true)
  const [tableList, setTableList] = useState(null)
  const [selectedTable, setSelectedTable] = useState(null)
  const [tableSchema, setTableSchema] = useState(null)
  const [tableData, setTableData] = useState(null)
  const [tableStats, setTableStats] = useState(null)
  const [relations, setRelations] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [activeTab, setActiveTab] = useState('overview')

  useEffect(() => {
    loadDataSummary()
  }, [])

  const loadDataSummary = async () => {
    setLoading(true)
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }

      const [listRes, relRes] = await Promise.all([
        axios.get('/api/v1/data-management/tables', { headers }),
        axios.get('/api/v1/data-management/relations', { headers })
      ])

      setTableList(listRes.data)
      setRelations(relRes.data)
    } catch (error) {
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadTableDetail = async (tableName) => {
    setSelectedTable(tableName)
    setLoading(true)
    try {
      const token = localStorage.getItem('token')
      const headers = { Authorization: `Bearer ${token}` }

      const [schemaRes, dataRes, statsRes] = await Promise.all([
        axios.get(`/api/v1/data-management/tables/${tableName}/schema`, { headers }),
        axios.get(`/api/v1/data-management/tables/${tableName}/preview`, {
          headers,
          params: { page: currentPage, page_size: pageSize }
        }),
        axios.get(`/api/v1/data-management/tables/${tableName}/stats`, { headers })
      ])

      setTableSchema(schemaRes.data)
      setTableData(dataRes.data)
      setTableStats(statsRes.data)
      setActiveTab('schema')
    } catch (error) {
      console.error('加载表详情失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const handlePageChange = (page, size) => {
    setCurrentPage(page)
    if (size) setPageSize(size)
    if (selectedTable) {
      loadTableDetail(selectedTable)
    }
  }

  // 概览页面
  const renderOverview = () => {
    if (!tableList) return <Empty description="加载中..." />

    return (
      <div>
        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card>
              <Statistic title="数据表总数" value={tableList.total_tables} prefix={<DatabaseOutlined />} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="总数据行数" value={tableList.total_rows} precision={0} prefix={<TableOutlined />} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="数仓分层数" value={6} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="表关系数" value={relations?.relations?.length || 0} prefix={<ApiOutlined />} />
            </Card>
          </Col>
        </Row>

        {/* 各层数据量 */}
        <Card title="📊 各层数据量分布" style={{ marginBottom: 24 }}>
          <Row gutter={16}>
            {Object.entries(tableList.grouped_tables).map(([layer, tables]) => (
              <Col span={8} key={layer}>
                <Card
                  size="small"
                  title={
                    <Space>
                      {LAYER_ICONS[layer]}
                      <Text strong style={{ color: LAYER_COLORS[layer] }}>{layer}</Text>
                    </Space>
                  }
                  style={{ marginBottom: 16 }}
                  extra={<Tag color={LAYER_COLORS[layer]}>{tables.length} 张表</Tag>}
                >
                  {tables.map(t => (
                    <div key={t.name} style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                      <Space>
                        <Button
                          type="link"
                          size="small"
                          icon={<EyeOutlined />}
                          onClick={() => loadTableDetail(t.name)}
                        >
                          {t.name}
                        </Button>
                      </Space>
                      <Tag color="blue">{t.row_count} 行</Tag>
                    </div>
                  ))}
                </Card>
              </Col>
            ))}
          </Row>
        </Card>

        {/* 数仓架构说明 */}
        <Alert
          message="四层数据仓库架构"
          description={
            <div>
              <Paragraph>
                <Text strong style={{ color: LAYER_COLORS['ODS层(原始数据)'] }}>● ODS (Operational Data Store) 原始数据层：</Text>
                存储媒体平台API返回的原始响应，保留完整溯源能力
              </Paragraph>
              <Paragraph>
                <Text strong style={{ color: LAYER_COLORS['DWD层(明细数据)'] }}>● DWD (Data Warehouse Detail) 明细数据层：</Text>
                字段标准化、数据清洗去重后的事实表
              </Paragraph>
              <Paragraph>
                <Text strong style={{ color: LAYER_COLORS['DWS层(聚合数据)'] }}>● DWS (Data Warehouse Summary) 聚合数据层：</Text>
                多维度指标聚合，ROI360核心宽表
              </Paragraph>
              <Paragraph>
                <Text strong style={{ color: LAYER_COLORS['ADS层(应用服务)'] }}>● ADS (Application Data Store) 应用服务层：</Text>
                面向业务场景，直接供前端使用的报表和缓存
              </Paragraph>
            </div>
          }
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />
      </div>
    )
  }

  // 表结构页面
  const renderSchema = () => {
    if (!tableSchema) return <Empty description="请先选择一张表" />

    return (
      <Space direction="vertical" style={{ width: '100%' }}>
        <Card
          title={
            <Space>
              <TableOutlined />
              <Text strong>{tableSchema.name}</Text>
              <Tag color="blue">{tableSchema.columns.length} 列</Tag>
              {tableSchema.primary_key.length > 0 && (
                <Tag color="gold">PK: {tableSchema.primary_key.join(', ')}</Tag>
              )}
            </Space>
          }
          extra={<Text type="secondary">{tableSchema.description}</Text>}
        >
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="主键">
              {tableSchema.primary_key.join(', ') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="外键数">
              {tableSchema.foreign_keys.length || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="索引数">
              {tableSchema.indexes.length || '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        {/* 列信息 */}
        <Card title="📋 列信息">
          <Table
            dataSource={tableSchema.columns}
            rowKey="name"
            size="small"
            pagination={false}
            columns={[
              {
                title: '列名',
                dataIndex: 'name',
                key: 'name',
                width: 200,
                render: (text, record) => (
                  <Space>
                    <Text strong>{text}</Text>
                    {record.is_primary_key && <Badge status="success" text="PK" />}
                    {!record.nullable && <Tag color="red">NOT NULL</Tag>}
                  </Space>
                )
              },
              { title: '数据类型', dataIndex: 'type', key: 'type', width: 150 },
              {
                title: '可空',
                dataIndex: 'nullable',
                key: 'nullable',
                width: 80,
                render: (v) => v ? '是' : '否'
              },
              { title: '默认值', dataIndex: 'default', key: 'default', ellipsis: true },
            ]}
          />
        </Card>

        {/* 外键关系 */}
        {tableSchema.foreign_keys.length > 0 && (
          <Card title="🔗 外键关系">
            <Table
              dataSource={tableSchema.foreign_keys}
              rowKey={(r, i) => i}
              size="small"
              pagination={false}
              columns={[
                { title: '本列', dataIndex: 'columns', key: 'col', render: v => v.join(', ') },
                { title: '→', key: 'arrow', render: () => '→' },
                { title: '关联表', dataIndex: 'ref_table', key: 'ref_table',
                  render: (text) => <Button type="link" onClick={() => loadTableDetail(text)}>{text}</Button>
                },
                { title: '关联列', dataIndex: 'ref_columns', key: 'ref_col', render: v => v.join(', ') },
              ]}
            />
          </Card>
        )}

        {/* 索引信息 */}
        {tableSchema.indexes.length > 0 && (
          <Card title="📑 索引信息">
            <Table
              dataSource={tableSchema.indexes}
              rowKey="name"
              size="small"
              pagination={false}
              columns={[
                { title: '索引名', dataIndex: 'name', key: 'name' },
                { title: '列', dataIndex: 'columns', key: 'col', render: v => v.join(', ') },
                { title: '唯一索引', dataIndex: 'unique', key: 'unique',
                  render: (v) => v ? <Tag color="green">是</Tag> : '否'
                },
              ]}
            />
          </Card>
        )}
      </Space>
    )
  }

  // 数据预览页面
  const renderDataPreview = () => {
    if (!tableData) return <Empty description="请先选择一张表" />

    return (
      <Card
        title={
          <Space>
            <TableOutlined />
            <Text strong>{tableData.table_name} - 数据预览</Text>
            <Tag color="blue">共 {tableData.total} 行</Tag>
          </Space>
        }
        extra={
          <Space>
            <Text type="secondary">第 {currentPage} 页</Text>
          </Space>
        }
      >
        <Table
          dataSource={tableData.rows}
          columns={tableData.columns.map(col => ({
            title: col,
            dataIndex: col,
            key: col,
            ellipsis: true,
            width: 150,
            render: (v) => {
              if (v === null) return <Text type="secondary">-</Text>
              if (typeof v === 'object') return <Text code>{JSON.stringify(v).substring(0, 50)}...</Text>
              if (typeof v === 'string' && v.length > 50) return v.substring(0, 50) + '...'
              return v
            }
          }))}
          rowKey={(r, i) => i}
          size="small"
          scroll={{ x: tableData.columns.length * 150 }}
          pagination={false}
        />
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={tableData.total}
            onChange={handlePageChange}
            showSizeChanger
            showTotal={(total) => `共 ${total} 行`}
          />
        </div>
      </Card>
    )
  }

  // 统计信息页面
  const renderStats = () => {
    if (!tableStats) return <Empty description="请先选择一张表" />

    const hasStats = Object.keys(tableStats.stats || {}).length > 0
    const hasDates = Object.keys(tableStats.date_ranges || {}).length > 0

    return (
      <Space direction="vertical" style={{ width: '100%' }}>
        <Card title="📈 数值列统计 (前5列)">
          {hasStats ? (
            <Row gutter={16}>
              {Object.entries(tableStats.stats).map(([col, stats]) => (
                <Col span={12} key={col}>
                  <Card size="small" title={col} style={{ marginBottom: 16 }}>
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="最小值">{stats.min?.toFixed(2) || '-'}</Descriptions.Item>
                      <Descriptions.Item label="最大值">{stats.max?.toFixed(2) || '-'}</Descriptions.Item>
                      <Descriptions.Item label="平均值">{stats.avg?.toFixed(2) || '-'}</Descriptions.Item>
                      <Descriptions.Item label="总和">{stats.sum?.toLocaleString() || '-'}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              ))}
            </Row>
          ) : (
            <Empty description="该表无可统计的数值列" />
          )}
        </Card>

        {hasDates && (
          <Card title="📅 时间列范围">
            <Row gutter={16}>
              {Object.entries(tableStats.date_ranges).map(([col, range]) => (
                <Col span={12} key={col}>
                  <Descriptions column={1} bordered size="small" title={col}>
                    <Descriptions.Item label="最早">{range.min || '-'}</Descriptions.Item>
                    <Descriptions.Item label="最晚">{range.max || '-'}</Descriptions.Item>
                  </Descriptions>
                </Col>
              ))}
            </Row>
          </Card>
        )}
      </Space>
    )
  }

  // 表关系图页面
  const renderRelations = () => {
    if (!relations) return <Empty description="加载中..." />

    return (
      <Card title="🔗 数据表关系图">
        <Row gutter={16}>
          <Col span={8}>
            <Card title="按层分组" size="small">
              {relations.groups.map(group => (
                <div key={group} style={{ marginBottom: 16 }}>
                  <Tag color={LAYER_COLORS[group]} style={{ marginBottom: 8 }}>
                    {LAYER_ICONS[group]} {group}
                  </Tag>
                  <div style={{ marginLeft: 8 }}>
                    {relations.tables
                      .filter(t => t.group === group)
                      .map(t => (
                        <Button
                          key={t.name}
                          type="link"
                          size="small"
                          onClick={() => loadTableDetail(t.name)}
                          style={{ display: 'block', textAlign: 'left' }}
                        >
                          {t.name}
                        </Button>
                      ))}
                  </div>
                </div>
              ))}
            </Card>
          </Col>
          <Col span={16}>
            <Card title="外键关系列表" size="small">
              <Table
                dataSource={relations.relations}
                rowKey={(r, i) => i}
                size="small"
                columns={[
                  {
                    title: '源表',
                    dataIndex: 'source_table',
                    key: 'src',
                    render: (text) => <Button type="link" size="small" onClick={() => loadTableDetail(text)}>{text}</Button>
                  },
                  { title: '源列', dataIndex: 'source_columns', key: 'src_col', render: v => v.join(', ') },
                  { title: '→', key: 'arrow', render: () => '→' },
                  {
                    title: '目标表',
                    dataIndex: 'target_table',
                    key: 'tgt',
                    render: (text) => <Button type="link" size="small" onClick={() => loadTableDetail(text)}>{text}</Button>
                  },
                  { title: '目标列', dataIndex: 'target_columns', key: 'tgt_col', render: v => v.join(', ') },
                ]}
                pagination={false}
              />
            </Card>
          </Col>
        </Row>
      </Card>
    )
  }

  if (loading && !tableList) {
    return (
      <div style={{ padding: 100, textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>加载数据管理中心...</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Title level={3} style={{ margin: 0 }}>
            <DatabaseOutlined /> 数据管理中心
          </Title>
          {selectedTable && (
            <Tag color="blue" style={{ marginLeft: 16 }}>
              当前表: {selectedTable}
              <Button type="link" size="small" onClick={() => setSelectedTable(null)}>
                清除
              </Button>
            </Tag>
          )}
        </Space>
        <Button onClick={loadDataSummary} size="small">刷新</Button>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="📊 数据概览" key="overview">
          {renderOverview()}
        </TabPane>
        <TabPane tab="📋 表结构" key="schema" disabled={!selectedTable}>
          {renderSchema()}
        </TabPane>
        <TabPane tab="🔍 数据预览" key="data" disabled={!selectedTable}>
          {renderDataPreview()}
        </TabPane>
        <TabPane tab="📈 统计信息" key="stats" disabled={!selectedTable}>
          {renderStats()}
        </TabPane>
        <TabPane tab="🔗 表关系图" key="relations">
          {renderRelations()}
        </TabPane>
      </Tabs>
    </div>
  )
}

export default DataManagement
