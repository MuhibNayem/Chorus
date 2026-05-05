import type { AgentEvent, ChatMessage, AgentActivity, ProjectProgress } from '$lib/types';

export type SSECallbacks = {
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
	onError?: (event: AgentEvent) => void;
	onComplete?: (event: AgentEvent) => void;
	onDownloadReady?: (event: AgentEvent) => void;
	onMessage?: (message: ChatMessage) => void;
	onRawEvent?: (event: AgentEvent) => void;
};

export class AGUIClient {
	private eventSource: EventSource | null = null;
	private callbacks: SSECallbacks;

	constructor(callbacks: SSECallbacks = {}) {
		this.callbacks = callbacks;
	}

	connect(projectId: string, message: string = '') {
		if (this.eventSource) {
			this.eventSource.close();
		}

		const url = message
			? `/api/stream/${projectId}?message=${encodeURIComponent(message)}`
			: `/api/stream/${projectId}`;
		this.eventSource = new EventSource(url);

		this.eventSource.onmessage = (event) => {
			try {
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
		this.callbacks.onRawEvent?.(event);

		switch (event.type) {
			case 'lifecycle':
				this.callbacks.onLifecycle?.(event);
				break;
			case 'step':
				this.callbacks.onStep?.(event);
				break;
			case 'text':
				this.callbacks.onText?.(event);
				this.callbacks.onMessage?.({
					id: crypto.randomUUID(),
					role: 'assistant',
					content: event.content || '',
					timestamp: event.timestamp || Date.now(),
					events: [event]
				});
				break;
			case 'tool_call':
				this.callbacks.onToolCall?.(event);
				break;
			case 'tool_result':
				this.callbacks.onToolResult?.(event);
				break;
			case 'state':
				this.callbacks.onState?.(event);
				break;
			case 'activity':
				if (event.agent_id && event.agent_name) {
					this.callbacks.onActivity?.({
						agent_id: event.agent_id,
						agent_name: event.agent_name,
						action: event.content || '',
						timestamp: event.timestamp || Date.now(),
						status: (event.data?.status as AgentActivity['status']) || 'working'
					});
				}
				break;
			case 'reasoning':
				this.callbacks.onReasoning?.(event);
				break;
			case 'thinking':
				this.callbacks.onThinking?.(event);
				break;
			case 'progress':
				this.callbacks.onProgress?.(event.data as unknown as ProjectProgress);
				break;
			case 'file_created':
			case 'file_modified':
				this.callbacks.onFileCreated?.(event);
				break;
			case 'error':
				this.callbacks.onError?.(event);
				break;
			case 'complete':
				this.callbacks.onComplete?.(event);
				break;
			case 'download_ready':
				this.callbacks.onDownloadReady?.(event);
				break;
		}
	}

	disconnect() {
		if (this.eventSource) {
			this.eventSource.close();
			this.eventSource = null;
		}
	}
}

export function parseAGUIEvent(raw: string): AgentEvent | null {
	try {
		return JSON.parse(raw) as AgentEvent;
	} catch {
		return null;
	}
}
