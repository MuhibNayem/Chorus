import type { AgentEvent, AgentStatus, TodoItem, ClaimInfo, ClaimStatus } from '$lib/types';

export type AgentEventType =
	| 'thinking'
	| 'context_built'
	| 'context_compacted'
	| 'text'
	| 'tool_start'
	| 'tool_call'
	| 'activity'
	| 'progress'
	| 'complete'
	| 'error'
	| 'retry'
	| 'lifecycle'
	| 'file_created'
	| 'file_modified'
	| 'directory_created'
	| 'download_ready'
	| 'state'
	| 'step'
	| 'tool_result'
	| 'agent_action'
	| 'reasoning'
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

export interface AgentStreamEvent {
	id: string;
	type: AgentEventType;
	content: string;
	timestamp: number;
	data?: Record<string, unknown>;
}

export interface AgentTask {
	name: string;
	completed: boolean;
	status: 'pending' | 'in_progress' | 'completed';
}

export interface AgentStream {
	id: string;
	name: string;
	status: AgentStatus;
	currentAction: string;
	thinking: string;
	textOutput: string;
	events: AgentStreamEvent[];
	toolCalls: AgentStreamEvent[];
	/** Progress derived from agent-authored todos (primary source) or backend step events (fallback). */
	progress: { percent: number; completed: number; total: number };
	/** Raw step data from backend 'progress' events — used when hasDynamicTodos is false. */
	stepProgress: { percent: number; completed: number; total: number };
	tasks: AgentTask[];
	claims: ClaimInfo[];
	createdAt: number;
	updatedAt: number;
	isExpanded: boolean;
	/** True once the agent has published its own todo list via a 'state' event. */
	hasDynamicTodos: boolean;
}

const DEFAULT_AGENTS: Record<string, { name: string; color: string }> = {
	'agent-rootdep': { name: 'Root Architect', color: '#8b5cf6' },
	'agent-backend': { name: 'Backend Specialist', color: '#3b82f6' },
	'agent-frontend': { name: 'Frontend Specialist', color: '#f59e0b' },
	'agent-devops': { name: 'DevOps Engineer', color: '#10b981' },
	'agent-packager': { name: 'Packager', color: '#ec4899' }
};

function createAgentStream(id: string, name: string): AgentStream {
	return {
		id,
		name,
		status: 'idle',
		currentAction: '',
		thinking: '',
		textOutput: '',
		events: [],
		toolCalls: [],
		progress: { percent: 0, completed: 0, total: 0 },
		stepProgress: { percent: 0, completed: 0, total: 0 },
		tasks: [],
		claims: [],
		createdAt: Date.now(),
		updatedAt: Date.now(),
		isExpanded: false,
		hasDynamicTodos: false
	};
}

/**
 * Recompute agent.progress from the authoritative source:
 *   - If the agent has published todos: exact todo completion ratio.
 *   - Otherwise: the last backend-reported step progress (stepProgress).
 * No "never-decrease" heuristic — we want recovery resets to be visible.
 */
function computeProgress(agent: AgentStream) {
	if (agent.hasDynamicTodos && agent.tasks.length > 0) {
		const completed = agent.tasks.filter((t) => t.status === 'completed').length;
		const total = agent.tasks.length;
		agent.progress = {
			percent: total > 0 ? Math.round((completed / total) * 100) : 0,
			completed,
			total
		};
	} else {
		// Mirror step progress from backend — already monotonic-clamped server-side.
		agent.progress = { ...agent.stepProgress };
	}
}

function syncTasksFromTodos(agent: AgentStream, todos: TodoItem[]) {
	agent.hasDynamicTodos = true;
	agent.tasks = todos.map((t) => ({
		name: t.content,
		completed: t.status === 'completed',
		status: t.status
	}));
	computeProgress(agent);
}

function syncClaimFromEvent(agent: AgentStream, event: AgentEvent) {
	const data = event.data;
	if (!data) return;

	const claimId = (data.claim_id as string) || '';
	const claimType = (data.claim_type as string) || '';
	const claimStatus = (data.claim_status as ClaimStatus) || 'claimed';
	const producerAgent = (data.producer_agent as string) || agent.name;

	if (!claimId && !claimType) return;

	const existingIndex = agent.claims.findIndex(
		(c) => c.claim_id === claimId || c.claim_type === claimType
	);

	const validation = data.validation as Record<string, unknown> | undefined;
	const errors = Array.isArray(validation?.errors)
		? (validation.errors as string[])
		: Array.isArray(data.errors)
			? (data.errors as string[])
				: [];

	const claimInfo: ClaimInfo = {
		claim_id: claimId,
		claim_type: claimType,
		claim_status: claimStatus,
		producer_agent: producerAgent,
		evidence_files: Array.isArray(data.evidence_files) ? (data.evidence_files as string[]) : undefined,
		validation_errors: errors.length > 0 ? errors : undefined,
		updated_at: event.timestamp || Date.now()
	};

	if (existingIndex >= 0) {
		agent.claims[existingIndex] = claimInfo;
	} else {
		agent.claims.push(claimInfo);
	}
}

function isClaimEventType(type: string): boolean {
	return [
		'claim_validated',
		'claim_invalid',
		'claim_stale',
		'claim_recovered',
		'verification_failed',
		'quarantined',
		'recovery_rollback'
	].includes(type);
}

class AgentRegistry {
	agents = $state<Record<string, AgentStream>>({});
	selectedAgentId = $state<string | null>(null);
	globalProgress = $state<{ percent: number; phase: string; message: string } | null>(null);
	downloadReady = $state(false);
	downloadData = $state<{ zip_url: string; download_url?: string; project_name: string; project_id: string } | null>(null);
	isRunning = $state(false);
	hasError = $state(false);
	errorMessage = $state('');

	get allAgents(): AgentStream[] {
		return Object.values(this.agents).sort((a, b) => a.createdAt - b.createdAt);
	}

	get activeAgents(): AgentStream[] {
		return this.allAgents.filter((a) => a.status === 'working' || a.status === 'thinking');
	}

	get selectedAgent(): AgentStream | null {
		return this.selectedAgentId ? this.agents[this.selectedAgentId] ?? null : null;
	}

	initialize() {
		this.agents = {};
		for (const [id, meta] of Object.entries(DEFAULT_AGENTS)) {
			this.agents[id] = createAgentStream(id, meta.name);
		}
		this.selectedAgentId = null;
		this.globalProgress = null;
		this.downloadReady = false;
		this.downloadData = null;
		this.isRunning = false;
		this.hasError = false;
		this.errorMessage = '';
	}

	registerAgent(id: string, name: string) {
		if (!this.agents[id]) {
			this.agents[id] = createAgentStream(id, name);
		}
	}

	selectAgent(id: string | null) {
		this.selectedAgentId = id;
	}

	dispatchEvent(event: AgentEvent) {
		const agentId = event.agent_id || 'agent-rootdep';
		const agentName = event.agent_name || DEFAULT_AGENTS[agentId]?.name || 'Unknown Agent';

		if (!this.agents[agentId]) {
			this.registerAgent(agentId, agentName);
		}

		const agent = this.agents[agentId];
		const streamEvent: AgentStreamEvent = {
			id: crypto.randomUUID(),
			type: event.type as AgentEventType,
			content: event.content || '',
			timestamp: event.timestamp || Date.now(),
			data: event.data
		};

		agent.updatedAt = Date.now();

		switch (event.type) {
			case 'progress': {
				// Update currentAction for UI display.
				agent.currentAction = event.content || agent.currentAction;

				// Consume the structured step data the backend emits on every tool completion.
				// Backend guarantees monotonic percent (server-side clamp), so we trust it directly.
				const d = event.data;
				if (typeof d?.percent === 'number') {
					agent.stepProgress = {
						percent: d.percent as number,
						completed: typeof d.completed_steps === 'number' ? (d.completed_steps as number) : agent.stepProgress.completed,
						total: typeof d.total_steps === 'number' ? (d.total_steps as number) : agent.stepProgress.total
					};
					// Only mirror to agent.progress when todos haven't taken over yet.
					if (!agent.hasDynamicTodos) {
						agent.progress = { ...agent.stepProgress };
					}
				}
				break;
			}

			case 'activity': {
				agent.status = (event.data?.status as AgentStatus) || 'working';
				agent.currentAction = event.content || '';
				agent.events.push(streamEvent);
				break;
			}

			case 'thinking':
			case 'reasoning': {
				agent.status = 'thinking';
				agent.thinking += event.content || '';
				agent.events.push({ ...streamEvent, content: event.content || '' });
				break;
			}

			case 'text': {
				agent.status = 'working';
				agent.textOutput += event.content || '';
				agent.events.push(streamEvent);
				break;
			}

			case 'tool_start':
			case 'tool_call':
			case 'agent_action':
			case 'tool_result': {
				agent.status = 'working';
				agent.toolCalls.push(streamEvent);
				agent.events.push(streamEvent);
				// Progress is driven by 'progress' events (step-based) and 'state' events
				// (todo-based) — no manual heuristic needed here.
				break;
			}

			case 'state': {
				// Agent-authored todo list — primary source of truth for progress.
				const todos = (event.data?.todos as TodoItem[]) || [];
				if (todos.length > 0) {
					syncTasksFromTodos(agent, todos);
				}
				agent.events.push(streamEvent);
				break;
			}

			case 'file_created':
			case 'file_modified': {
				agent.events.push(streamEvent);
				break;
			}

			case 'complete': {
				agent.status = 'complete';
				agent.currentAction = 'Task finished';
				agent.events.push(streamEvent);
				// Mark all remaining tasks complete in the task list.
				for (const task of agent.tasks) {
					task.completed = true;
					task.status = 'completed';
				}
				// Always 100% on completion — regardless of todo/step tracking state.
				const total = agent.tasks.length || agent.progress.total || 1;
				agent.progress = { percent: 100, completed: total, total };
				break;
			}

			case 'error': {
				agent.status = 'error';
				agent.currentAction = event.content || 'An error occurred';
				agent.events.push(streamEvent);
				this.hasError = true;
				this.errorMessage = event.content || 'An error occurred';
				break;
			}

			case 'warning': {
				agent.currentAction = event.content || 'Warning';
				agent.events.push(streamEvent);
				break;
			}

			case 'claim_validated':
			case 'claim_invalid':
			case 'claim_stale':
			case 'claim_recovered':
			case 'verification_failed':
			case 'quarantined':
			case 'recovery_rollback': {
				syncClaimFromEvent(agent, event);
				agent.events.push(streamEvent);
				if (event.type === 'quarantined') {
					agent.status = 'error';
					agent.currentAction = event.content || 'Agent quarantined';
					this.hasError = true;
					this.errorMessage = event.content || 'Agent quarantined';
				}
				break;
			}

			case 'retry': {
				agent.status = 'working';
				agent.currentAction = event.content || 'Retrying...';
				agent.events.push(streamEvent);
				break;
			}

			case 'download_ready': {
				this.downloadReady = true;
				this.downloadData = event.data as {
					zip_url: string;
					download_url?: string;
					project_name: string;
					project_id: string;
				};
				this.isRunning = false;
				break;
			}

			case 'RunFinished': {
				this.isRunning = false;
				break;
			}

			case 'RunError': {
				this.isRunning = false;
				this.hasError = true;
				this.errorMessage = event.content || 'Project generation failed';
				break;
			}

			case 'RunStarted': {
				// isRunning is set in handleSubmit
				break;
			}

			case 'agent_paused': {
				agent.status = 'paused';
				agent.currentAction = event.content || 'Paused — waiting for your input';
				agent.events.push(streamEvent);
				break;
			}

			case 'agent_resumed': {
				agent.status = 'working';
				agent.currentAction = event.content || 'Resumed';
				agent.events.push(streamEvent);
				break;
			}

			case 'agent_stopped':
			case 'stopped': {
				agent.status = 'stopped';
				agent.currentAction = event.content || 'Stopped by user';
				agent.events.push(streamEvent);
				break;
			}

			case 'swarm_stop_requested': {
				// Mark all non-complete agents as stopped
				for (const a of Object.values(this.agents)) {
					if (a.status !== 'complete') {
						a.status = 'stopped';
						a.currentAction = 'Stopped by user';
					}
				}
				this.isRunning = false;
				break;
			}

			case 'directive_received':
			case 'directive_queued':
			case 'pause_requested':
			case 'resume_requested': {
				agent.events.push(streamEvent);
				break;
			}

			default: {
				agent.events.push(streamEvent);
				break;
			}
		}
	}

	reset() {
		this.initialize();
	}
}

export const agentRegistry = new AgentRegistry();
