import { useCallback, useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Image,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { EventQuery } from '../api'
import type { AppConfig, EventDetail, HazardEvent } from '../types'
import { REJECT_REASONS } from '../types'

const STATUS: Record<string, { color: string; text: string }> = {
  draft: { color: 'processing', text: '待复核' },
  confirmed: { color: 'success', text: '已确认' },
  rejected: { color: 'default', text: '已驳回' },
}

const LEVEL_COLOR: Record<string, string> = {
  一般隐患: 'gold',
  较大隐患: 'orange',
  重大隐患: 'red',
}

export default function BoardPage() {
  const { message } = AntApp.useApp()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [items, setItems] = useState<HazardEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState<EventQuery>({ only_hazard: true, limit: 200 })
  const [rejecting, setRejecting] = useState<HazardEvent | null>(null)
  const [detail, setDetail] = useState<EventDetail | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.events(filters)
      setItems(res.items)
    } catch (e) {
      message.error(String(e))
    } finally {
      setLoading(false)
    }
  }, [filters, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined)
  }, [])

  // 支持从任务详情页带 ?event=xxx 直接打开详情
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('event')
    if (!id) return
    api
      .event(id)
      .then(setDetail)
      .catch((e: unknown) => message.error(String(e)))
  }, [message])

  const nameOf = (code: string | null) =>
    config?.categories.find((c) => c.id === code)?.name ?? code ?? '—'

  const confirmEvent = async (event: HazardEvent) => {
    try {
      await api.review(event.event_id, {
        event_id: event.event_id,
        action: 'confirm',
        reviewer: 'inspector',
      })
      message.success('已确认')
      void load()
    } catch (e) {
      message.error(String(e))
    }
  }

  const submitReject = async () => {
    if (!rejecting) return
    const values = await form.validateFields()
    try {
      await api.review(rejecting.event_id, {
        event_id: rejecting.event_id,
        action: 'reject',
        reason_code: values.reason_code,
        note: values.note ?? '',
        reviewer: 'inspector',
      })
      message.success('已驳回，原因已入库（用于后续调优）')
      setRejecting(null)
      form.resetFields()
      void load()
    } catch (e) {
      message.error(String(e))
    }
  }

  const columns: ColumnsType<HazardEvent> = [
    {
      title: '证据',
      dataIndex: 'evidence_url',
      width: 110,
      render: (url: string | null) =>
        url ? (
          <Image src={url} className="evidence-thumb" preview={{ src: url }} />
        ) : (
          <Typography.Text type="secondary">无</Typography.Text>
        ),
    },
    {
      title: '隐患类别',
      key: 'type',
      width: 190,
      render: (_, row) => (
        <Space direction="vertical" size={2}>
          <Space size={4}>
            <Tag color="geekblue">{row.hazard_type ?? '—'}</Tag>
            {row.duplicate_of && <Tag>重复</Tag>}
          </Space>
          <Typography.Text style={{ fontSize: 12 }}>{nameOf(row.hazard_type)}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '等级',
      dataIndex: 'level',
      width: 110,
      render: (level: string | null) => (
        <Tag color={LEVEL_COLOR[level ?? ''] ?? 'default'}>{level ?? '未定级'}</Tag>
      ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 90,
      render: (v: number) => `${(v * 100).toFixed(0)}%`,
    },
    {
      title: '判定理由',
      dataIndex: 'reason',
      render: (text: string, row) => (
        <Space direction="vertical" size={2}>
          <Typography.Paragraph
            style={{ marginBottom: 0, fontSize: 13 }}
            ellipsis={{ rows: 2, tooltip: text }}
          >
            {text}
          </Typography.Paragraph>
          {row.sop_pending && <Tag color="warning">判据待专家确认</Tag>}
        </Space>
      ),
    },
    { title: '点位', dataIndex: 'point_id', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => (
        <Tag color={STATUS[s]?.color ?? 'default'}>{STATUS[s]?.text ?? s}</Tag>
      ),
    },
    { title: '时间', dataIndex: 'created_at', width: 165 },
    {
      title: '操作',
      key: 'action',
      width: 190,
      fixed: 'right',
      render: (_, row) => (
        <Space size={4}>
          <Button
            size="small"
            type="link"
            onClick={() => void api.event(row.event_id).then(setDetail)}
          >
            详情
          </Button>
          <Popconfirm
            title="确认这条隐患？"
            onConfirm={() => void confirmEvent(row)}
            disabled={row.status !== 'draft'}
          >
            <Button size="small" type="link" disabled={row.status !== 'draft'}>
              确认
            </Button>
          </Popconfirm>
          <Button
            size="small"
            type="link"
            danger
            disabled={row.status !== 'draft'}
            onClick={() => {
              form.resetFields()
              setRejecting(row)
            }}
          >
            驳回
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="隐患看板"
      extra={
        <Space wrap>
          <Select
            allowClear
            placeholder="点位"
            style={{ width: 140 }}
            value={filters.point_id}
            onChange={(v?: string) => setFilters((f) => ({ ...f, point_id: v }))}
            options={(config?.points ?? []).map((p) => ({ value: p.id, label: p.name }))}
          />
          <Select
            allowClear
            placeholder="类别"
            style={{ width: 180 }}
            value={filters.hazard_type}
            onChange={(v?: string) => setFilters((f) => ({ ...f, hazard_type: v }))}
            options={(config?.categories ?? [])
              .filter((c) => c.in_mvp)
              .map((c) => ({ value: c.id, label: `${c.id} ${c.name}` }))}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={filters.status}
            onChange={(v?: string) => setFilters((f) => ({ ...f, status: v }))}
            options={[
              { value: 'draft', label: '待复核' },
              { value: 'confirmed', label: '已确认' },
              { value: 'rejected', label: '已驳回' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
          <Button type="primary" href={api.exportUrl} target="_blank">
            导出 CSV
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="event_id"
        columns={columns}
        dataSource={items}
        loading={loading}
        scroll={{ x: 1400 }}
        pagination={{ pageSize: 10 }}
        locale={{ emptyText: '暂无隐患事件' }}
      />

      <Modal
        open={Boolean(rejecting)}
        title="驳回隐患"
        okText="提交驳回"
        okButtonProps={{ danger: true }}
        onOk={() => void submitReject()}
        onCancel={() => setRejecting(null)}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          驳回原因会进入误报案例集，用于提示词与规则调优，请如实选择。
        </Typography.Paragraph>
        <Form form={form} layout="vertical">
          <Form.Item
            name="reason_code"
            label="驳回原因"
            rules={[{ required: true, message: '请选择驳回原因' }]}
          >
            <Select options={REJECT_REASONS} placeholder="必选" />
          </Form.Item>
          <Form.Item name="note" label="补充说明">
            <Input.TextArea rows={3} maxLength={200} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={Boolean(detail)}
        width={720}
        title={detail ? `隐患详情 · ${detail.hazard_type ?? '未分类'}` : ''}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {detail.evidence_url && <Image src={detail.evidence_url} width="100%" />}
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="事件ID">{detail.event_id}</Descriptions.Item>
              <Descriptions.Item label="点位">{detail.point_id}</Descriptions.Item>
              <Descriptions.Item label="类别">
                {detail.hazard_type} {nameOf(detail.hazard_type)}
              </Descriptions.Item>
              <Descriptions.Item label="等级">{detail.level ?? '未定级'}</Descriptions.Item>
              <Descriptions.Item label="置信度">
                {(detail.confidence * 100).toFixed(0)}%
              </Descriptions.Item>
              <Descriptions.Item label="判定理由">{detail.reason}</Descriptions.Item>
              <Descriptions.Item label="依据条款">
                {detail.sop_ref ?? '待专家确认'}
              </Descriptions.Item>
              <Descriptions.Item label="处置建议">{detail.action ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="模型/版本">
                {detail.engine.model_id} · prompt {detail.engine.prompt_version} · 规则{' '}
                {detail.engine.rule_version}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {STATUS[detail.status]?.text ?? detail.status}
                {detail.degraded && (
                  <Tag color="red" style={{ marginLeft: 8 }}>
                    降级
                  </Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="时间">{detail.created_at}</Descriptions.Item>
            </Descriptions>
            {detail.reviews.length > 0 && (
              <Card size="small" title="复核记录">
                {detail.reviews.map((r) => (
                  <div key={r.created_at}>
                    {r.created_at} · {r.action === 'confirm' ? '确认' : `驳回（${r.reason_code}）`}
                    {r.note ? ` · ${r.note}` : ''}
                  </div>
                ))}
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </Card>
  )
}


