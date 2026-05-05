export type AgentStatus = 'idle' | 'working' | 'thinking' | 'complete' | 'error';

export interface AgentState {
	id: string;
	name: string;
	status: AgentStatus;
	currentAction: string;
	events: AgentEvent[];
	isExpanded: boolean;
}

export type AgentEventType =
	| 'lifecycle'
	| 'step'
	| 'text'
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
	| 'error'
	| 'complete'
	| 'download_ready'
	| 'retry'
	| 'RunStarted'
	| 'RunFinished'
	| 'RunError';

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
