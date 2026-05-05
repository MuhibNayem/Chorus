<script lang="ts">
	import type { AgentStream } from '$lib/agent-registry.svelte';
	import AgentBlock from './AgentBlock.svelte';

	let {
		agents,
		selectedId,
		onSelect
	}: {
		agents: AgentStream[];
		selectedId: string | null;
		onSelect: (id: string) => void;
	} = $props();

	// Only show real swarm agents (filter out system/ghost agents)
	const knownAgentIds = new Set([
		'agent-rootdep',
		'agent-backend',
		'agent-frontend',
		'agent-devops',
		'agent-packager'
	]);

	const swarmAgents = $derived(agents.filter((a) => knownAgentIds.has(a.id)));
	const activeAgents = $derived(swarmAgents.filter((a) => a.status !== 'idle'));
	const idleAgents = $derived(swarmAgents.filter((a) => a.status === 'idle'));
</script>

<div class="space-y-6">
	<!-- Active Agents Section -->
	{#if activeAgents.length > 0}
		<div class="animate-fade-in">
			<div class="flex items-center gap-2 mb-4 px-1">
				<div class="h-2 w-2 rounded-full bg-primary animate-pulse"></div>
				<h3 class="text-xs font-bold uppercase tracking-[0.15em] text-muted-foreground/70">Active Agents</h3>
				<span class="text-[10px] text-muted-foreground/40 font-mono">{activeAgents.length}</span>
			</div>
			<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
				{#each activeAgents as agent (agent.id)}
					<AgentBlock
						{agent}
						isSelected={selectedId === agent.id}
						onSelect={onSelect}
					/>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Idle Agents Section -->
	{#if idleAgents.length > 0}
		<div class="animate-fade-in">
			<div class="flex items-center gap-2 mb-4 px-1">
				<div class="h-2 w-2 rounded-full bg-slate-400/40"></div>
				<h3 class="text-xs font-bold uppercase tracking-[0.15em] text-muted-foreground/70">Idle Agents</h3>
				<span class="text-[10px] text-muted-foreground/40 font-mono">{idleAgents.length}</span>
			</div>
			<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
				{#each idleAgents as agent (agent.id)}
					<AgentBlock
						{agent}
						isSelected={selectedId === agent.id}
						onSelect={onSelect}
					/>
				{/each}
			</div>
		</div>
	{/if}

	{#if swarmAgents.length === 0}
		<div class="flex flex-col items-center justify-center py-24 text-muted-foreground/40 animate-fade-in">
			<div class="h-16 w-16 rounded-2xl border-2 border-dashed border-muted-foreground/20 flex items-center justify-center mb-5 bg-muted/20">
				<span class="text-3xl">🤖</span>
			</div>
			<p class="text-sm font-medium">No agents registered yet</p>
			<p class="text-xs mt-1.5 text-muted-foreground/30">Start a project to see the swarm come alive</p>
		</div>
	{/if}
</div>
