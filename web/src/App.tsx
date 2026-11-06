import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Alert, Layout, Menu, Space, Tag, Typography } from 'antd'
import {
  AlertOutlined,
  BarChartOutlined,
  UnorderedListOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { api } from './api'
import type { Health } from './types'
import UploadPage from './pages/UploadPage'
import TasksPage from './pages/TasksPage'
import TaskDetailPage from './pages/TaskDetailPage'
import BoardPage from './pages/BoardPage'
import StatsPage from './pages/StatsPage'

const { Header, Content, Sider } = Layout

const NAV = [
  { key: '/upload', icon: <UploadOutlined />, label: <Link to="/upload">上传巡检</Link> },
  { key: '/tasks', icon: <UnorderedListOutlined />, label: <Link to="/tasks">巡检任务</Link> },
  { key: '/board', icon: <AlertOutlined />, label: <Link to="/board">隐患看板</Link> },
  { key: '/stats', icon: <BarChartOutlined />, label: <Link to="/stats">统计</Link> },
]

export default function App() {
  const location = useLocation()
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: unknown) => setError(String(e)))
  }, [])

  const selected = NAV.find((item) => location.pathname.startsWith(item.key))?.key ?? '/upload'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{ display: 'flex', alignItems: 'center', gap: 16, background: '#0f2b46', paddingInline: 20 }}
      >
        <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
          化工巡检 · 隐患识别
        </Typography.Title>
        <Space wrap>
          {health && (
            <Tag color={health.mock ? 'orange' : 'green'}>
              {health.mock ? 'Mock 模式（无 Key 演示）' : health.model}
            </Tag>
          )}
          {health && <Tag color="blue">{health.network_mode}</Tag>}
          {health && <Tag>规则 {health.rules_version}</Tag>}
        </Space>
      </Header>
      <Layout>
        <Sider width={184} theme="light">
          <Menu
            mode="inline"
            selectedKeys={[selected]}
            items={NAV}
            style={{ height: '100%', paddingTop: 8 }}
          />
        </Sider>
        <Content>
          <div className="page">
            {error && (
              <Alert
                type="error"
                showIcon
                message="后端连接失败"
                description={`${error}　请确认已运行 ./scripts/dev.sh`}
                style={{ marginBottom: 16 }}
              />
            )}
            <Routes>
              <Route path="/" element={<Navigate to="/upload" replace />} />
              <Route path="/upload" element={<UploadPage />} />
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
              <Route path="/board" element={<BoardPage />} />
              <Route path="/stats" element={<StatsPage />} />
              <Route path="*" element={<Navigate to="/upload" replace />} />
            </Routes>
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
