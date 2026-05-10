export type AgentStatus = 'idle' | 'working' | 'thinking' | 'complete' | 'error' | 'paused' | 'stopped';

export interface AgentState {
	id: string;
	name: string;
	status: AgentStatus;
	currentAction: string;
	events: AgentEvent[];
	isExpanded: boolean;
}

export type ClaimStatus = 'claimed' | 'valid' | 'invalid' | 'stale' | 'revoked';

export interface ClaimInfo {
	claim_id: string;
	claim_type: string;
	claim_status: ClaimStatus;
	producer_agent: string;
	evidence_files?: string[];
	validation_errors?: string[];
	updated_at?: number;
}

export type AgentEventType =
	| 'lifecycle'
	| 'step'
	| 'text'
	| 'question'
	| 'context_built'
	| 'context_compacted'
	| 'tool_call'
	| 'tool_result'
	| 'tool_start'
	| 'state'
	| 'activity'
	| 'reasoning'
	| 'agent_action'
	| 'thinking'
	| 'progress'
	| 'file_created'
	| 'file_modified'
	| 'directory_created'
	| 'error'
	| 'warning'
	| 'complete'
	| 'download_ready'
	| 'retry'
	| 'RunStarted'
	| 'RunFinished'
	| 'RunError'
	| 'PlanReady'
	// Claim protocol telemetry events (Phase 8)
	| 'claim_validated'
	| 'claim_invalid'
	| 'claim_stale'
	| 'claim_recovered'
	| 'verification_failed'
	| 'quarantined'
	| 'recovery_rollback'
	| 'checkpoint'
	| 'checkpoint_before_retry'
	| 'checkpoint_on_error'
  | 'agent_paused'
  | 'agent_resumed'
  | 'agent_stopped'
  | 'stopped'
  | 'swarm_stop_requested'
  | 'directive_received'
  | 'directive_queued'
  | 'pause_requested'
  | 'resume_requested';

export interface AgentEvent {
	type: AgentEventType;
	agent_id?: string;
	agent_name?: string;
	content?: string;
	data?: Record<string, unknown>;
	timestamp?: number;
}

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	timestamp: number;
	metadata?: Record<string, any>;
	events?: AgentEvent[];
}

export interface AgentActivity {
	agent_id: string;
	agent_name: string;
	action: string;
	timestamp: number;
	status: 'thinking' | 'working' | 'complete' | 'error';
}

export interface TodoItem {
	status: 'pending' | 'in_progress' | 'completed';
	content: string;
}

export interface ProjectProgress {
	phase: 'parsing' | 'planning' | 'generating' | 'building' | 'packaging' | 'complete';
	percent: number;
	message: string;
	agents?: AgentActivity[];
}
