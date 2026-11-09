import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { AppConfig } from '../types'

export default function UploadPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [pointId, setPointId] = useState<string>()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api
      .config()
      .then((c) => {
        setConfig(c)
        setPointId(c.points[0]?.id)
      })
      .catch((e: unknown) => message.error(String(e)))
  }, [message])

  const point = config?.points.find((p) => p.id === pointId)
  const mvpCategories = (config?.categories ?? []).filter((c) => c.in_mvp)

  const submit = async () => {
    if (!pointId) {
      message.warning('请先选择点位')
      return
    }
    const files: File[] = []
    fileList.forEach((item) => {
      if (item.originFileObj) files.push(item.originFileObj)
    })
    if (files.length === 0) {
      message.warning('请至少选择一张图片')
      return
    }
    setSubmitting(true)
    try {
      const task = await api.createTask({ point_id: pointId, source: 'image' })
      const res = await api.uploadFrames(task.task_id, files)
      const dedup = res.frames.filter((f) => f.dedup).length
      message.success(
        `已提交 ${res.accepted} 张${dedup ? `（重复 ${dedup} 张已跳过）` : ''}`,
      )
      navigate(`/tasks/${task.task_id}`)
    } catch (e) {
      message.error(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {config && !config.criteria_confirmed && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前判定判据为开发侧草稿，尚未经化工专家确认"
          description="事件仍会生成，但全部标注「判据条款待专家确认」并强制人工复核。拿到标准原文后修改 config/hazard_taxonomy.yaml 即生效。"
        />
      )}

      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title="上传巡检图片" extra={<Tag color="blue">图片 / 可多选</Tag>}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div>
                <Typography.Text strong>巡检点位</Typography.Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  placeholder="选择点位"
                  value={pointId}
                  onChange={setPointId}
                  options={(config?.points ?? []).map((p) => ({
                    value: p.id,
                    label: `${p.name}（${p.id}）`,
                  }))}
                />
              </div>

              <Upload.Dragger
                multiple
                accept="image/*"
                fileList={fileList}
                beforeUpload={() => false}
                onChange={({ fileList: next }) => setFileList(next)}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">点击或拖拽图片到此处</p>
                <p className="ant-upload-hint">
                  支持一次多张；相同图片会按 sha256 自动去重，不重复消耗模型调用
                </p>
              </Upload.Dragger>

              <Space>
                <Button type="primary" loading={submitting} onClick={submit}>
                  提交并识别
                </Button>
                <Button onClick={() => setFileList([])} disabled={!fileList.length}>
                  清空
                </Button>
                <Typography.Text type="secondary">共 {fileList.length} 张</Typography.Text>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="点位上下文（影响判定准确率）" style={{ marginBottom: 16 }}>
            {point ? (
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="点位">{point.name}</Descriptions.Item>
                <Descriptions.Item label="编号">{point.id}</Descriptions.Item>
                <Descriptions.Item label="区域">{point.zone ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="位置">{point.location_hint ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="应有设施">
                  {(point.facilities ?? []).join('；') || '—'}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Typography.Text type="secondary">请选择点位</Typography.Text>
            )}
          </Card>

          <Card title="本次检查项">
            {config?.check_items?.enabled && (
              <div style={{ marginBottom: 12 }}>
                <Tag color="purple">45 项试点</Tag>
                {config.check_items.items.map((item) => (
                  <div key={item.code} style={{ marginTop: 8 }}>
                    <Space size={4} wrap>
                      <Tag color="geekblue">{item.code}</Tag>
                      <span>{item.name}</span>
                      <Tag>{item.sub_items.length} 子项</Tag>
                    </Space>
                    <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                      {item.sub_items.map((s) => `${s.code} ${s.name}`).join('；')}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <Space direction="vertical" size={4}>
              {mvpCategories.map((c) => (
                <Space key={c.id}>
                  <Tag color="geekblue">{c.id}</Tag>
                  <span>{c.name}</span>
                  <Tag>{c.level ?? '未定级'}</Tag>
                </Space>
              ))}
              {mvpCategories.length === 0 && (
                <Typography.Text type="secondary">未配置 MVP 检查项</Typography.Text>
              )}
            </Space>
          </Card>
        </Col>
      </Row>
    </>
  )
}
