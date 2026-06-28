import React, { useState } from 'react'
import { Form, Input, Button, Card, Typography, Space } from 'antd'
import { RocketOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

function Login({ onLogin }) {
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (values) => {
    setLoading(true)
    await onLogin(values.email, values.password)
    setLoading(false)
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
    }}>
      <Card style={{ width: 400, boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <RocketOutlined style={{ fontSize: 48, color: '#1890ff', marginBottom: 16 }} />
          <Title level={2} style={{ margin: 0 }}>SmartUA</Title>
          <Text type="secondary">智能投放平台 - 大模型驱动</Text>
        </div>

        <Form
          onFinish={handleSubmit}
          layout="vertical"
          initialValues={{ email: 'optimizer1@smartua.com', password: '123456' }}
        >
          <Form.Item
            label="邮箱"
            name="email"
            rules={[{ required: true, type: 'email', message: '请输入正确的邮箱' }]}
          >
            <Input placeholder="请输入邮箱" />
          </Form.Item>

          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block size="large">
              登录
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Text type="secondary">
            优化师: optimizer1@smartua.com / 123456
            <br />
            管理员: admin@smartua.com / 123456
          </Text>
        </div>
      </Card>
    </div>
  )
}

export default Login
