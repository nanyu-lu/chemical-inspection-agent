import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { App as AntApp, Button, Card, Progress, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { TaskSummary } from '../types'

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  done: 'success',
  failed: 'error',
}
const STATUS_TEXT: Record<string, string> = {
  pending: '排队中',
  running: '识别中',
  done: '已完成',
  failed: '失败',
}

export default function TasksPage() {
  const { message } = AntApp.useApp()
  const [rows, setRows] = useState<TaskSummary[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await api.tasks())
    } catch (e) {
      message.error(String(e))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), 5000)
    return () => clearInterval(timer)
  }, [load])

  const columns: ColumnsType<TaskSummary> = [
    {
      title: '任务',
      dataIndex: 'task_id',
      render: (id: string) => <Link to={`/tasks/${id}`}>{id.slice(0, 8)}</Link>,
    },
    { title: '点位', dataIndex: 'point_id' },
    {
      title: '进度',
      key: 'progress',
      width: 200,
      render: (_, row) => (
        <Space direction="vertical" size={0} style={{ width: '100%' }}>
          <Progress
            percent={
              row.total_frames ? Math.round((row.done_frames / row.total_frames) * 100) : 0
            }
            size="small"
            status={row.status === 'failed' ? 'exception' : undefined}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.done_frames} / {row.total_frames} 帧
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (s: string) => <Tag color={STATUS_COLOR[s] ?? 'default'}>{STATUS_TEXT[s] ?? s}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 190 },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, row) => <Link to={`/tasks/${row.task_id}`}>查看</Link>,
    },
  ]

  return (
    <Card
      title="巡检任务"
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
          刷新
        </Button>
      }
    >
      <Table
        rowKey="task_id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 10 }}
        locale={{ emptyText: '暂无任务，先去「上传巡检」创建' }}
      />
    </Card>
  )
}
