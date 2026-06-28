import React from 'react'
import { Layout, Menu, Avatar, Dropdown, Button, Space, Badge } from 'antd'
import {
  DashboardOutlined,
  ThunderboltOutlined,
  UserOutlined,
  LogoutOutlined,
  BellOutlined,
  DatabaseOutlined,
  ApiOutlined,
  VideoCameraOutlined
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'

const { Header, Sider, Content } = Layout

function MainLayout({ children, user, onLogout }) {
  const navigate = useNavigate()
  const location = useLocation()

  const currentApp = { name: 'Block Blast' }

  const menuItems = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '投放大盘' },
    { key: '/intent', icon: <ThunderboltOutlined />, label: '意图操作中心' },
    { key: '/creatives', icon: <VideoCameraOutlined />, label: '素材管理' },
    { key: '/data-management', icon: <DatabaseOutlined />, label: '数据管理中心' },
    { key: '/connectors', icon: <ApiOutlined />, label: '连接器管理' },
  ]

  const userMenuItems = [
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout }
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ 
        background: '#fff', 
        padding: '0 24px', 
        display: 'flex', 
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #f0f0f0'
      }}>
        <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#1890ff' }}>
          🚀 SmartUA 智能投放平台
        </div>
        <Space size="large">
          {currentApp && (
            <Button type="primary" size="small">
              当前应用: {currentApp.name}
            </Button>
          )}
          <Badge count={3} size="small">
            <BellOutlined style={{ fontSize: '18px', cursor: 'pointer' }} />
          </Badge>
          <Dropdown menu={{ items: userMenuItems }}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.username || user?.email}</span>
            </Space>
          </Dropdown>
        </Space>
      </Header>
      <Layout>
        <Sider width={200} style={{ background: '#fff' }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            style={{ height: '100%', borderRight: 0 }}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
          />
        </Sider>
        <Layout style={{ padding: '24px' }}>
          <Content style={{ background: '#fff', padding: 24, margin: 0, minHeight: 280 }}>
            {children}
          </Content>
        </Layout>
      </Layout>
    </Layout>
  )
}

export default MainLayout
