// 与后端 JSON 一致的契约类型（后端 schemas 是唯一事实来源，这里只做镜像）

export type EventStatus = 'draft' | 'confirmed' | 'rejected'

export interface Category {
  id: string
  name: string
  in_mvp: boolean
  vision_detectable?: string | null
  level?: string | null
}

export interface PointInfo {
  id: string
  name: string
  zone?: string
  location_hint?: string
  facilities?: string[]
  focus?: string[]
}

export interface AppConfig {
  categories: Category[]
  points: PointInfo[]
  thresholds: { conf_drop: number; conf_review: number }
  criteria_confirmed: boolean
}

export interface Detection {
  hazard_type: string
  score: number
  bbox: number[] | null
  source: string
  bbox_space: string
}

export interface HazardEvent {
  event_id: string
  task_id: string
  point_id: string
  hazard_type: string | null
  is_hazard: boolean
  level: string | null
  confidence: number
  reason: string
  sop_ref: string | null
  sop_pending: boolean
  action: string | null
  status: EventStatus
  need_manual_review: boolean
  degraded: boolean
  duplicate_of: string | null
  evidence_url: string | null
  detections: Detection[]
  engine: { model_id: string; prompt_version: string; rule_version: string }
  created_at: string
}

export interface TaskFrame {
  frame_id: string
  status: string
  error: string | null
  url: string | null
  width: number
  height: number
  captured_at: string
  event: HazardEvent | null
}

export interface TaskSummary {
  task_id: string
  point_id: string
  route_id: string | null
  robot_id: string
  source: string
  status: string
  total_frames: number
  done_frames: number
  created_at: string
  finished_at: string | null
}

export interface TaskDetail extends TaskSummary {
  frames: TaskFrame[]
}

export interface Stats {
  frames: number
  events: number
  hazards: number
  need_review: number
  degraded: number
  by_hazard_type: Record<string, number>
  by_point: Record<string, number>
  usage: { prompt_tokens: number; completion_tokens: number; avg_latency_ms: number }
}

export interface Health {
  status: string
  network_mode: string
  model: string
  client: string
  mock: boolean
  rules_version: string
  points: string[]
}

export interface ReviewItem {
  action: string
  reason_code: string | null
  note: string
  reviewer: string
  created_at: string
}

export interface EventDetail extends HazardEvent {
  reviews: ReviewItem[]
}

export const REJECT_REASONS: { value: string; label: string }[] = [
  { value: 'false_positive', label: '误报：画面里没有该隐患' },
  { value: 'not_hazard', label: '有该现象但依标准不算隐患' },
  { value: 'unclear', label: '看不清，无法判定' },
  { value: 'wrong_category', label: '类别判错' },
  { value: 'already_handled', label: '已整改 / 已闭环' },
  { value: 'other', label: '其他（请备注）' },
]
