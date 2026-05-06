import type { AgentEvent, AgentStatus, TodoItem } from '$lib/types';

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
	| 'download_ready'
	| 'state'
	| 'step'
	| 'tool_result'
	| 'agent_action'
	| 'reasoning'
	| 'RunStarted'
	| 'RunFinished'
	| 'RunError'
	| 'PlanReady';

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
	progress: { percent: number; completed: number; total: number };
	tasks: AgentTask[];
	createdAt: number;
	updatedAt: number;
	isExpanded: boolean;
	/** True if this agent has authored its own todo list via state events */
	hasDynamicTodos: boolean;
	/** Number of unique tool calls made (fallback progress when no todos) */
	toolCallCount: number;
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
		tasks: [],
		createdAt: Date.now(),
		updatedAt: Date.now(),
		isExpanded: false,
		hasDynamicTodos: false,
		toolCallCount: 0
	};
}

function computeProgress(agent: AgentStream) {
	if (agent.hasDynamicTodos && agent.tasks.length > 0) {
		// Agent-authored todo list is the source of truth
		const completed = agent.tasks.filter((t) => t.status === 'completed').length;
		const total = agent.tasks.length;
		const newPercent = total > 0 ? Math.round((completed / total) * 100) : 0;
		// Never decrease percent — only increase or stay same
		agent.progress = {
			percent: Math.max(agent.progress.percent, newPercent),
			completed,
			total
		};
	} else if (agent.toolCallCount > 0) {
		// Fallback: use tool call count as rough progress
		// We don't know the total, so we use a heuristic that grows slowly
		const estimatedTotal = Math.max(agent.toolCallCount, 3);
		const percent = Math.min(90, Math.round((agent.toolCallCount / estimatedTotal) * 100));
		agent.progress = {
			percent: Math.max(agent.progress.percent, percent),
			completed: agent.toolCallCount,
			total: estimatedTotal
		};
	} else {
		agent.progress = { percent: 0, completed: 0, total: 0 };
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
				// Backend step-based progress is ignored — we use agent-authored todos
				agent.currentAction = event.content || agent.currentAction;
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

				// Count unique tool calls for fallback progress
				if (event.type === 'tool_call' || event.type === 'tool_result') {
					agent.toolCallCount++;
					if (!agent.hasDynamicTodos) {
						computeProgress(agent);
					}
				}
				break;
			}

			case 'state': {
				// Agent-authored state update — this is the primary todo source
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
				// Mark all remaining tasks as completed
				for (const task of agent.tasks) {
					task.completed = true;
					task.status = 'completed';
				}
				computeProgress(agent);
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
				// Ignored — isRunning is set in handleSubmit
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
