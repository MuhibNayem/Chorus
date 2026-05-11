<script lang="ts">
	interface Agent {
		id: string;
		name: string;
		status: 'idle' | 'working' | 'thinking' | 'complete' | 'error' | 'paused' | 'stopped';
		currentAction: string;
		progress: { percent: number; completed: number; total: number };
	}

	interface Props {
		agents: Agent[];
		onSelectAgent?: (id: string) => void;
		selectedAgentId?: string | null;
	}

	let { agents, onSelectAgent, selectedAgentId }: Props = $props();

	function getInitial(name: string): string {
		return name.charAt(0).toUpperCase();
	}

	function getGradient(id: string): string {
		const map: Record<string, string> = {
			'agent-rootdep': 'linear-gradient(135deg, #a78bfa, #7c3aed)',
			'agent-backend': 'linear-gradient(135deg, #22d3ee, #0891b2)',
			'agent-frontend': 'linear-gradient(135deg, #f472b6, #db2777)',
			'agent-devops': 'linear-gradient(135deg, #fbbf24, #d97706)',
			'agent-packager': 'linear-gradient(135deg, #34d399, #059669)',
		};
		return map[id] || 'linear-gradient(135deg, #94a3b8, #475569)';
	}

	function getStatusLabel(status: string): string {
		const map: Record<string, string> = {
			'working': 'writing',
			'thinking': 'thinking',
			'complete': 'ready',
			'error': 'review',
			'paused': 'queued',
			'stopped': 'idle',
			'idle': 'idle',
		};
		return map[status] || status;
	}

	function getStatusClass(status: string): string {
		if (status === 'working' || status === 'thinking') return 'run';
		if (status === 'complete') return 'done';
		return 'idle';
	}
</script>

<div class="agent-status-panel">
	<h6>Swarm</h6>
	{#each agents as agent}
		<button
			type="button"
			class="agent-row {getStatusClass(agent.status)} {selectedAgentId === agent.id ? 'selected' : ''}"
			onclick={() => onSelectAgent?.(agent.id)}
		>
			<span class="av" style="background: {getGradient(agent.id)}">{getInitial(agent.name)}</span>
			<span class="name">{agent.name.replace(/Specialist|Engineer/g, '').trim().toLowerCase().replace(/\s+/g, '_')}</span>
			<span class="stat">{getStatusLabel(agent.status)}</span>
		</button>
	{:else}
		<div class="empty">No agents active</div>
	{/each}

	{#if agents.some(a => a.status === 'working' || a.status === 'thinking')}
		<div class="progress-wrap">
			<div class="progress-track">
				<div class="progress-fill" style="width: {Math.round(
					agents.filter(a => a.status === 'complete').length / agents.length * 100
				)}%"></div>
			</div>
			<div class="progress-label">
				{agents.filter(a => a.status === 'complete').length}/{agents.length} complete
			</div>
		</div>
	{/if}
</div>

<style>
	.agent-status-panel {
		height: 100%;
		overflow-y: auto;
		padding: 16px 14px;
		font-family: var(--font-mono);
		font-size: 11.5px;
		color: rgba(255,255,255,0.6);
		background: rgba(255,255,255,0.02);
		border-left: 1px solid rgba(255,255,255,0.06);
	}
	.agent-status-panel::-webkit-scrollbar { width: 4px; }
	.agent-status-panel::-webkit-scrollbar-thumb {
		background: rgba(255,255,255,0.1);
		border-radius: 4px;
	}

	h6 {
		margin: 0 0 12px;
		font-size: 10.5px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: rgba(255,255,255,0.55);
		font-weight: 500;
	}

	.agent-row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px;
		border-radius: 10px;
		margin-bottom: 6px;
		border: 1px solid rgba(255,255,255,0.06);
		background: transparent;
		cursor: pointer;
		width: 100%;
		text-align: left;
		transition: background 150ms ease, border-color 150ms ease;
	}
	.agent-row:hover {
		background: rgba(255,255,255,0.04);
		border-color: rgba(255,255,255,0.10);
	}
	.agent-row.selected {
		background: rgba(167,139,250,0.10);
		border-color: rgba(167,139,250,0.20);
	}

	.av {
		width: 26px;
		height: 26px;
		border-radius: 8px;
		display: grid;
		place-items: center;
		font-size: 10px;
		color: white;
		font-weight: 600;
		flex-shrink: 0;
	}

	.name {
		color: white;
		font-size: 11.5px;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.stat {
		margin-left: auto;
		font-size: 10px;
		color: rgba(255,255,255,0.55);
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.stat::before {
		content: "";
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 999px;
		background: rgba(255,255,255,0.30);
	}

	.agent-row.run .stat::before {
		background: oklch(75% 0.16 150);
		box-shadow: 0 0 6px oklch(75% 0.16 150);
		animation: pulseGlow 1.4s infinite;
	}
	.agent-row.done .stat::before {
		background: var(--cyan);
		box-shadow: 0 0 6px var(--cyan);
	}

	@keyframes pulseGlow {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.empty {
		padding: 20px 8px;
		text-align: center;
		color: rgba(255,255,255,0.30);
		font-size: 11px;
	}

	.progress-wrap {
		margin-top: 12px;
		padding-top: 12px;
		border-top: 1px solid rgba(255,255,255,0.06);
	}
	.progress-track {
		height: 3px;
		background: rgba(255,255,255,0.08);
		border-radius: 2px;
		overflow: hidden;
	}
	.progress-fill {
		height: 100%;
		background: var(--violet);
		border-radius: 2px;
		transition: width 400ms ease;
	}
	.progress-label {
		margin-top: 6px;
		font-size: 10px;
		color: rgba(255,255,255,0.40);
		text-align: right;
	}
</style>
