import type {
  AppConfig,
  EventDetail,
  HazardEvent,
  Health,
  Stats,
  TaskDetail,
  TaskSummary,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      /* 非 JSON 错误体，保留 statusText */
    }
    throw new Error(`${res.status} ${detail}`)
  }
  return (await res.json()) as T
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') sp.set(k, String(v))
  })
  return sp.toString()
}

export type EventQuery = {
  point_id?: string
  hazard_type?: string
  status?: string
  only_hazard?: boolean
  limit?: number
  offset?: number
}

export const api = {
  health: () => request<Health>('/api/v1/health'),

  config: () => request<AppConfig>('/api/v1/config'),

  createTask: (body: { point_id: string; route_id?: string; source?: string }) =>
    request<TaskSummary>('/api/v1/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  uploadFrames: (taskId: string, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return request<{ accepted: number; frames: { frame_id: string; dedup: boolean }[] }>(
      `/api/v1/tasks/${taskId}/frames`,
      { method: 'POST', body: fd },
    )
  },

  tasks: () => request<TaskSummary[]>('/api/v1/tasks?limit=50'),

  task: (taskId: string) => request<TaskDetail>(`/api/v1/tasks/${taskId}`),

  events: (query: EventQuery) =>
    request<{ total: number; items: HazardEvent[] }>(`/api/v1/events?${qs(query)}`),

  event: (eventId: string) => request<EventDetail>(`/api/v1/events/${eventId}`),

  review: (eventId: string, body: Record<string, unknown>) =>
    request<{ event_id: string; status: string }>(`/api/v1/events/${eventId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  stats: () => request<Stats>('/api/v1/stats'),

  exportUrl: '/api/v1/export/events.csv',
}
