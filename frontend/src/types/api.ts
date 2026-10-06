/**
 * Fathom API Types and Shared Enums.
 * Strictly mirrors backend/app/enums.py and backend/app/schemas.py.
 */

export type SpanStatus = 
  | 'running'
  | 'completed'
  | 'failed'
  | 'rewound'
  | 'pending'
  | 'skipped'
  | 'cancelled';

export type SpanKind = 
  | 'llm_call'
  | 'tool_call'
  | 'retrieval'
  | 'processing'
  | 'agent_decision';

export type EvaluationPhase = 
  | 'tool_check'
  | 'semantic_drift'
  | 'judge_llm';

export type EvaluationVerdict = 
  | 'pass'
  | 'warning'
  | 'failure'
  | 'error';

export type RunStatus = 
  | 'running'
  | 'completed'
  | 'failed'
  | 'rewound';

export interface EvaluationResponse {
  id: string;
  span_id: string;
  phase: EvaluationPhase;
  verdict: EvaluationVerdict;
  score: number | null;
  details: Record<string, any>;
  summary: string | null;
  evaluator_version?: string | null;
  evaluator_model?: string | null;
  prompt_hash?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface SpanResponse {
  id: string;
  run_id: string;
  parent_span_id: string | null;
  name: str;
  kind: SpanKind;
  status: SpanStatus;
  input_data: Record<string, any>;
  output_data: Record<string, any>;
  error_message: string | null;
  latency_ms: number;
  token_count: number;
  model_name: string | null;
  metadata: Record<string, any>;
  started_at?: string | null;
  ended_at?: string | null;
  rewind_group_id?: string | null;
  rewind_depth?: number;
  origin_span_id?: string | null;
  side_effects?: string;
  cost_usd?: number | null;
  created_at: string;
  updated_at: string;
  evaluations: EvaluationResponse[];
  effective_verdict?: EvaluationVerdict | null;
  is_root_cause?: boolean;
  root_cause_type?: 'originating' | 'propagated' | null;
}

// Helper type alias
type str = string;

export interface RunResponse {
  id: string;
  name: string;
  status: RunStatus;
  total_tokens: number;
  total_latency_ms: number;
  metadata: Record<string, any>;
  has_rewinds: boolean;
  active_group_id: string | null;
  created_at: string;
  updated_at: string;
  span_count: number;
}

export interface SpanLinkResponse {
  id: string;
  run_id: string;
  from_span_id: string;
  to_span_id: string;
  link_type: string;
}

export interface RootCauseAttribution {
  span_id: string;
  confidence: number;
  path: string[];
  explanation: string;
}

export interface DagResponse {
  run: RunResponse;
  spans: SpanResponse[];
  root_span_ids: string[];
  links: SpanLinkResponse[];
  root_cause: RootCauseAttribution | null;
}

export interface RewindRequest {
  span_id: string;
  mutated_input: Record<string, any>;
  re_execute?: boolean;
}

export interface RewindResponse {
  success: boolean;
  rewind_group_id: string;
  rewound_span_id: string;
  downstream_re_executed: string[];
  downstream_pending_confirmation: string[];
  downstream_skipped: string[];
  estimated_tokens: number;
  status: string;
  new_run_id: string | null;
  message: string;
}
