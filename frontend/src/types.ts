export type Service = {
  id: number
  name: string
  description: string
  type: string
  status: string
  pid: number | null
  restart_count: number
  health_check_type: string
  health_check_url: string
  expected_content: string
  restart_policy: string
  max_restart_attempts: number
  auto_remediation: boolean
  ai_diagnosis: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export type Incident = {
  id: number
  service_id: number
  type: string
  severity: string
  status: string
  error_message: string
  exit_code: number | null
  restart_attempts: number
  recovery_verified: boolean
  detected_at: string
  resolved_at: string | null
  duration_sec: number | null
  fingerprint: string
}

export type TimelineEvent = { t: string; type: string; message: string; meta: Record<string, unknown> }

export type Diagnosis = {
  id: number
  incident_id: number
  source: string
  model: string
  root_cause: string
  confidence: number
  risk: string
  recommendation: string
  t: string
}
