import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Alert,
  Badge,
  Card,
  Col,
  Descriptions,
  Empty,
  Image,
  Progress,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { api } from '../api'
import type { TaskDetail } from '../types'

const STATUS_TEXT: Record<string, string> = {
  pending: '排队中',
  running: '识别中',
  done: '已完成',
  failed: '失败',
}

export default function TaskDetailPage() {
  const { taskId = '' } = useParams()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setTask(await api.task(taskId))
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [taskId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!task || task.status === 'done' || task.status === 'failed') return
    const timer = setInterval(() => void load(), 2000)
    return () => clearInterval(timer)
  }, [task, load])

  if (error) {
    return <Alert type="error" showIcon message="加载任务失败" description={error} />
  }

  if (!task) {
    return (
      <Card>
        <Spin /> <Typography.Text style={{ marginLeft: 8 }}>加载中…</Typography.Text>
      </Card>
    )
  }

  const hazards = task.frames.filter((f) => f.event?.is_hazard).length

  return (
    <>
      <Card
        title={
          <Space>
            <span>任务 {task.task_id.slice(0, 8)}</span>
            <Tag color={task.status === 'done' ? 'success' : task.status === 'failed' ? 'error' : 'processing'}>
              {STATUS_TEXT[task.status] ?? task.status}
            </Tag>
          </Space>
        }
        extra={<Link to="/tasks">返回列表</Link>}
        style={{ marginBottom: 16 }}
      >
        <Descriptions column={4} size="small">
          <Descriptions.Item label="点位">{task.point_id}</Descriptions.Item>
          <Descriptions.Item label="来源">{task.source}</Descriptions.Item>
          <Descriptions.Item label="识别隐患">{hazards} 条</Descriptions.Item>
          <Descriptions.Item label="创建时间">{task.created_at}</Descriptions.Item>
        </Descriptions>
        <Progress
          percent={task.total_frames ? Math.round((task.done_frames / task.total_frames) * 100) : 0}
          status={task.status === 'failed' ? 'exception' : undefined}
        />
      </Card>

      {task.frames.length === 0 ? (
        <Card>
          <Empty description="该任务还没有帧数据" />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {task.frames.map((frame) => {
            const event = frame.event
            return (
              <Col key={frame.frame_id} xs={24} sm={12} lg={8} xl={6}>
                <Card
                  size="small"
                  title={
                    <Badge
                      status={frame.status === 'done' ? 'success' : frame.status === 'failed' ? 'error' : 'processing'}
                      text={frame.status === 'done' ? '已识别' : frame.status === 'failed' ? '失败' : '处理中'}
                    />
                  }
                  extra={
                    event?.is_hazard ? (
                      <Tag color="red">{event.hazard_type}</Tag>
                    ) : event ? (
                      <Tag color="green">未见隐患</Tag>
                    ) : null
                  }
                >
                  {frame.url ? (
                    <Image
                      src={frame.url}
                      width="100%"
                      style={{ height: 150, objectFit: 'cover', borderRadius: 4 }}
                      placeholder
                    />
                  ) : (
                    <div style={{ height: 150, background: '#f0f0f0', borderRadius: 4 }} />
                  )}

                  {event && event.is_hazard ? (
                    <Space direction="vertical" size={4} style={{ marginTop: 8 }}>
                      <Space size={4} wrap>
                        <Tag color="orange">{event.level ?? '未定级'}</Tag>
                        <Tag>置信度 {(event.confidence * 100).toFixed(0)}%</Tag>
                        {event.sop_pending && <Tag color="warning">判据待确认</Tag>}
                      </Space>
                      <Typography.Paragraph
                        style={{ marginBottom: 0, fontSize: 12 }}
                        ellipsis={{ rows: 3 }}
                      >
                        {event.reason}
                      </Typography.Paragraph>
                      <Link to={`/board?event=${event.event_id}`}>去复核 →</Link>
                    </Space>
                  ) : (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {frame.error ?? '本次未发现检查项内隐患'}
                    </Typography.Text>
                  )}
                </Card>
              </Col>
            )
          })}
        </Row>
      )}
    </>
  )
}
