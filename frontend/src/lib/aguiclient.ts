import type { AgentEvent, ChatMessage, AgentActivity, ProjectProgress } from '$lib/types';

export type SSECallbacks = {
	onOpen?: (projectId: string) => void;
	onLifecycle?: (event: AgentEvent) => void;
	onStep?: (event: AgentEvent) => void;
	onText?: (event: AgentEvent) => void;
	onToolCall?: (event: AgentEvent) => void;
	onToolResult?: (event: AgentEvent) => void;
	onState?: (event: AgentEvent) => void;
	onActivity?: (activity: AgentActivity) => void;
	onReasoning?: (event: AgentEvent) => void;
	onThinking?: (event: AgentEvent) => void;
	onProgress?: (progress: ProjectProgress) => void;
	onFileCreated?: (event: AgentEvent) => void;
	onFileModified?: (event: AgentEvent) => void;
	onDirectoryCreated?: (event: AgentEvent) => void;
	onError?: (event: AgentEvent) => void;
	onComplete?: (event: AgentEvent) => void;
	onDownloadReady?: (event: AgentEvent) => void;
	onPlanReady?: (event: AgentEvent) => void;
	onMessage?: (message: ChatMessage) => void;
	onRawEvent?: (event: AgentEvent) => void;
	onQuestion?: (event: AgentEvent) => void;
	onAgentPaused?: (event: AgentEvent) => void;
	onAgentResumed?: (event: AgentEvent) => void;
	onSwarmStopped?: (event: AgentEvent) => void;
};

export class AGUIClient {
	private eventSource: EventSource | null = null;
	private callbacks: SSECallbacks;
	private currentProjectId: string | null = null;
	private lastEventIdFor(projectId: string) {
		return `chorus.lastEventId.${projectId}`;
	}

	constructor(callbacks: SSECallbacks = {}) {
		this.callbacks = callbacks;
	}

	connect(projectId: string, contextMode: string = 'auto', mode: string = 'generate', uiMode: string = 'build') {
		if (this.eventSource) {
			this.eventSource.close();
		}
		this.currentProjectId = projectId;

		const params = new URLSearchParams();
		if (contextMode) params.set('context_mode', contextMode);
		if (mode) params.set('mode', mode);
		if (uiMode) params.set('ui_mode', uiMode);
		if (typeof sessionStorage !== 'undefined') {
			const lastEventId = sessionStorage.getItem(this.lastEventIdFor(projectId));
			if (lastEventId) params.set('since_event_id', lastEventId);
		}

		const query = params.toString();
		const url = query ? `/api/stream/${projectId}?${query}` : `/api/stream/${projectId}`;
		this.eventSource = new EventSource(url);
		this.eventSource.onopen = () => {
			this.callbacks.onOpen?.(projectId);
		};

		this.eventSource.onmessage = (event) => {
			try {
				if (event.lastEventId && typeof sessionStorage !== 'undefined') {
					sessionStorage.setItem(this.lastEventIdFor(projectId), event.lastEventId);
				}
				const data = JSON.parse(event.data) as AgentEvent;
				this.handleEvent(data);
			} catch (e) {
				console.error('Failed to parse SSE event:', e);
			}
		};

		this.eventSource.onerror = (error) => {
			console.error('SSE error:', error);
			this.callbacks.onError?.({
				type: 'error',
				content: 'Connection error'
			});
		};
	}

	private handleEvent(event: AgentEvent) {
		const normalizedEvent: AgentEvent = {
			...event,
			timestamp:
				typeof event.timestamp === 'string'
					? new Date(event.timestamp).getTime()
					: event.timestamp
		};
		this.callbacks.onRawEvent?.(normalizedEvent);

		switch (normalizedEvent.type) {
			case 'lifecycle':
				this.callbacks.onLifecycle?.(normalizedEvent);
				break;
			case 'step':
				this.callbacks.onStep?.(normalizedEvent);
				break;
			case 'text':
				this.callbacks.onText?.(normalizedEvent);
				this.callbacks.onMessage?.({
					id: crypto.randomUUID(),
					role: 'assistant',
					content: normalizedEvent.content || '',
					timestamp: normalizedEvent.timestamp || Date.now(),
					events: [normalizedEvent]
				});
				break;
			case 'tool_call':
				this.callbacks.onToolCall?.(normalizedEvent);
				break;
			case 'tool_result':
				this.callbacks.onToolResult?.(normalizedEvent);
				break;
			case 'state':
				this.callbacks.onState?.(normalizedEvent);
				break;
			case 'activity':
				if (normalizedEvent.agent_id && normalizedEvent.agent_name) {
					this.callbacks.onActivity?.({
						agent_id: normalizedEvent.agent_id,
						agent_name: normalizedEvent.agent_name,
						action: normalizedEvent.content || '',
						timestamp: normalizedEvent.timestamp || Date.now(),
						status:
							(normalizedEvent.data?.status as AgentActivity['status']) ||
							'working'
					});
				}
				break;
			case 'reasoning':
				this.callbacks.onReasoning?.(normalizedEvent);
				break;
			case 'thinking':
				this.callbacks.onThinking?.(normalizedEvent);
				break;
			case 'progress':
				this.callbacks.onProgress?.(
					normalizedEvent.data as unknown as ProjectProgress
				);
				break;
			case 'file_created':
			case 'file_modified':
				this.callbacks.onFileCreated?.(normalizedEvent);
				break;
			case 'directory_created':
				this.callbacks.onDirectoryCreated?.(normalizedEvent);
				break;
			case 'error':
				this.callbacks.onError?.(normalizedEvent);
				break;
			case 'complete':
				this.callbacks.onComplete?.(normalizedEvent);
				break;
			case 'download_ready':
				this.callbacks.onDownloadReady?.(normalizedEvent);
				break;
			case 'RunFinished':
				this.callbacks.onComplete?.(normalizedEvent);
				this.disconnect();
				break;
			case 'RunError':
				this.callbacks.onError?.(normalizedEvent);
				this.disconnect();
				break;
			case 'PlanReady':
				this.callbacks.onPlanReady?.(normalizedEvent);
				this.disconnect();
				break;
			case 'question':
				this.callbacks.onQuestion?.(normalizedEvent);
				break;
			case 'agent_paused':
				this.callbacks.onAgentPaused?.(normalizedEvent);
				break;
			case 'agent_resumed':
				this.callbacks.onAgentResumed?.(normalizedEvent);
				break;
			case 'swarm_stop_requested':
			case 'agent_stopped':
			case 'stopped':
				this.callbacks.onSwarmStopped?.(normalizedEvent);
				break;
			case 'directive_received':
			case 'directive_queued':
			case 'pause_requested':
			case 'resume_requested':
				this.callbacks.onRawEvent?.(normalizedEvent);
				break;
		}
	}

	disconnect() {
		if (this.eventSource) {
			this.eventSource.close();
			this.eventSource = null;
		}
		this.currentProjectId = null;
	}
}

export function parseAGUIEvent(raw: string): AgentEvent | null {
	try {
		return JSON.parse(raw) as AgentEvent;
	} catch {
		return null;
	}
}
