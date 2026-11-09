import { useEffect, useState } from 'react'
import { App as AntApp, Card, Col, Progress, Row, Space, Statistic, Tag, Typography } from 'antd'
import { api } from '../api'
import type { AppConfig, Stats } from '../types'

export default function StatsPage() {
  const { message } = AntApp.useApp()
  const [stats, setStats] = useState<Stats | null>(null)
  const [config, setConfig] = useState<AppConfig | null>(null)

  useEffect(() => {
    api
      .stats()
      .then(setStats)
      .catch((e: unknown) => message.error(String(e)))
    api.config().then(setConfig).catch(() => undefined)
  }, [message])

  const nameOf = (code: string) => {
    const legacy = config?.categories.find((c) => c.id === code)?.name
    if (legacy) return legacy
    const item = config?.check_items?.items.find((i) => code.startsWith(i.code))
    return item ? `${item.name}（${code}）` : code
  }

  const maxOf = (record: Record<string, number>) =>
    Math.max(1, ...Object.values(record))

  if (!stats) {
    return <Card loading />
  }

  const typeRows = Object.entries(stats.by_hazard_type).sort((a, b) => b[1] - a[1])
  const pointRows = Object.entries(stats.by_point).sort((a, b) => b[1] - a[1])

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={12} md={8} xl={4}>
          <Card size="small">
            <Statistic title="巡检帧数" value={stats.frames} />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={4}>
          <Card size="small">
            <Statistic title="隐患事件" value={stats.hazards} valueStyle={{ color: '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={4}>
          <Card size="small">
            <Statistic title="待人工复核" value={stats.need_review} valueStyle={{ color: '#d46b08' }} />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={4}>
          <Card size="small">
            <Statistic title="降级事件" value={stats.degraded} />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={4}>
          <Card size="small">
            <Statistic title="平均时延" value={stats.usage.avg_latency_ms} suffix="ms" />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={4}>
          <Card size="small">
            <Statistic
              title="累计 Token"
              value={stats.usage.prompt_tokens + stats.usage.completion_tokens}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card size="small" title="按隐患类别">
            {typeRows.length === 0 && <Typography.Text type="secondary">暂无数据</Typography.Text>}
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {typeRows.map(([code, count]) => (
                <div key={code}>
                  <Space>
                    <Tag color="geekblue">{code}</Tag>
                    <span>{nameOf(code)}</span>
                    <Typography.Text strong>{count}</Typography.Text>
                  </Space>
                  <Progress
                    percent={Math.round((count / maxOf(stats.by_hazard_type)) * 100)}
                    showInfo={false}
                    size="small"
                  />
                </div>
              ))}
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card size="small" title="按点位">
            {pointRows.length === 0 && <Typography.Text type="secondary">暂无数据</Typography.Text>}
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {pointRows.map(([point, count]) => (
                <div key={point}>
                  <Space>
                    <span>{point}</span>
                    <Typography.Text strong>{count}</Typography.Text>
                  </Space>
                  <Progress
                    percent={Math.round((count / maxOf(stats.by_point)) * 100)}
                    showInfo={false}
                    size="small"
                    strokeColor="#52c41a"
                  />
                </div>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>

      <Card size="small" title="指标说明">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13 }}>
          「隐患事件」为模型判定的隐患条数，全部需人工确认后才生效；
          「待人工复核」为尚未确认/驳回的条数；「降级事件」为模型不可用时的转人工记录。
          当前**没有正常样本集，因此不展示误报率**——补齐 50 张以上无隐患现场图后可计算精确率。
        </Typography.Paragraph>
      </Card>
    </Space>
  )
}
