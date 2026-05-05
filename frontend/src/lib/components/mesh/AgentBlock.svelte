<script lang="ts">
	import type { AgentStream } from '$lib/agent-registry.svelte';
	import StatusPulse from './StatusPulse.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Card, CardContent } from '$lib/components/ui/card';
	import {
		Bot,
		Brain,
		Wrench,
		MessageSquare,
		ChevronRight,
		Terminal,
		Sparkles,
		Database,
		Layout,
		Network,
		Server,
		Code
	} from 'lucide-svelte';

	let {
		agent,
		isSelected,
		onSelect
	}: {
		agent: AgentStream;
		isSelected: boolean;
		onSelect: (id: string) => void;
	} = $props();

	const agentTheme = $derived(
		agent.id === 'agent-rootdep'
			? { icon: Network, cardBg: 'from-violet-100/90 to-violet-50/50', glow: 'shadow-[0_4px_20px_rgba(139,92,246,0.25)]', glowSelected: 'shadow-[0_4px_35px_rgba(139,92,246,0.5)]', badge: 'bg-white/60 text-violet-700 border-transparent', iconBg: 'bg-violet-200 text-violet-700' }
			: agent.id === 'agent-backend'
				? { icon: Database, cardBg: 'from-sky-100/90 to-sky-50/50', glow: 'shadow-[0_4px_20px_rgba(14,165,233,0.25)]', glowSelected: 'shadow-[0_4px_35px_rgba(14,165,233,0.5)]', badge: 'bg-white/60 text-sky-700 border-transparent', iconBg: 'bg-sky-200 text-sky-700' }
				: agent.id === 'agent-frontend'
					? { icon: Layout, cardBg: 'from-amber-100/90 to-amber-50/50', glow: 'shadow-[0_4px_20px_rgba(245,158,11,0.25)]', glowSelected: 'shadow-[0_4px_35px_rgba(245,158,11,0.5)]', badge: 'bg-white/60 text-amber-700 border-transparent', iconBg: 'bg-amber-200 text-amber-700' }
					: agent.id === 'agent-devops'
						? { icon: Server, cardBg: 'from-emerald-100/90 to-emerald-50/50', glow: 'shadow-[0_4px_20px_rgba(16,185,129,0.25)]', glowSelected: 'shadow-[0_4px_35px_rgba(16,185,129,0.5)]', badge: 'bg-white/60 text-emerald-700 border-transparent', iconBg: 'bg-emerald-200 text-emerald-700' }
						: { icon: Code, cardBg: 'from-pink-100/90 to-pink-50/50', glow: 'shadow-[0_4px_20px_rgba(236,72,153,0.25)]', glowSelected: 'shadow-[0_4px_35px_rgba(236,72,153,0.5)]', badge: 'bg-white/60 text-pink-700 border-transparent', iconBg: 'bg-pink-200 text-pink-700' }
	);

	const isActive = $derived(agent.status === 'working' || agent.status === 'thinking');
	const hasThinking = $derived(agent.thinking.length > 0);
	const hasTools = $derived(agent.toolCalls.length > 0);
	const hasText = $derived(agent.textOutput.length > 0);
	const latestEvents = $derived(agent.events.slice(-3));
	
	const Icon = $derived(agentTheme.icon);
</script>

<button
	type="button"
	class="group relative w-full text-left transition-all duration-300 {isSelected ? 'scale-[1.02]' : 'hover:scale-[1.01]'}"
	onclick={() => onSelect(agent.id)}
>
	<Card
		class="rounded-3xl ring-0 relative overflow-hidden border-0 bg-gradient-to-br {agentTheme.cardBg} backdrop-blur-xl transition-all duration-500 {agentTheme.glow} {isSelected ? agentTheme.glowSelected + ' scale-[1.01]' : 'hover:scale-[1.005]'}"
	>
		<!-- Animated gradient top border for active agents -->
		{#if isActive}
			<div class="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-primary/60 to-transparent animate-shimmer"></div>
		{/if}

		<CardContent class="p-4 space-y-3">
			<!-- Header -->
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-3">
					<div class="flex h-10 w-10 items-center justify-center rounded-[14px] {agentTheme.iconBg} shadow-sm">
						<Icon class="h-5 w-5" />
					</div>
					<div class="min-w-0">
						<h3 class="text-sm font-semibold tracking-tight truncate">{agent.name}</h3>
						<div class="flex items-center gap-2 mt-0.5">
							<StatusPulse status={agent.status} size="sm" />
							<span class="text-[11px] text-muted-foreground/70 capitalize">{agent.status}</span>
						</div>
					</div>
				</div>
				<ChevronRight class="h-4 w-4 text-muted-foreground/40 transition-all duration-300 group-hover:text-muted-foreground group-hover:translate-x-0.5" />
			</div>

			<!-- Current Action -->
			{#if agent.currentAction}
				<div class="flex items-start gap-2 rounded-lg bg-muted/40 px-2.5 py-1.5">
					<Terminal class="h-3 w-3 mt-0.5 shrink-0 text-muted-foreground/60" />
					<span class="text-xs text-muted-foreground line-clamp-2 leading-relaxed">{agent.currentAction}</span>
				</div>
			{/if}

			<!-- Mini Event Stream -->
			{#if latestEvents.length > 0}
				<div class="h-px bg-border/30"></div>
				<div class="space-y-1.5">
					{#each latestEvents as event (event.id)}
						<div class="flex items-center gap-2 text-xs">
							{#if event.type === 'thinking'}
								<Brain class="h-3 w-3 shrink-0 text-amber-400/80" />
								<span class="text-amber-400/80 truncate">Thinking...</span>
							{:else if event.type === 'tool_call' || event.type === 'tool_start'}
								<Wrench class="h-3 w-3 shrink-0 text-sky-400/80" />
								<span class="text-sky-400/80 truncate">{event.content || event.type}</span>
							{:else if event.type === 'text'}
								<MessageSquare class="h-3 w-3 shrink-0 text-emerald-400/80" />
								<span class="text-emerald-400/80 truncate">{event.content?.slice(0, 60) || 'Output'}</span>
							{:else if event.type === 'error'}
								<span class="text-rose-400/80 truncate">{event.content || 'Error'}</span>
							{:else}
								<span class="text-muted-foreground/60 truncate">{event.content || event.type}</span>
							{/if}
						</div>
					{/each}
				</div>
			{/if}

			<!-- Dynamic Todo List -->
			{#if agent.tasks.length > 0}
				<div class="space-y-1.5">
					<div class="flex items-center justify-between">
						<span class="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">Tasks</span>
						<span class="text-[10px] font-mono text-muted-foreground/50">{agent.progress.percent}%</span>
					</div>
					{#each agent.tasks as todo, i (i)}
						<div class="flex items-start gap-2 rounded-md px-2 py-1 transition-all duration-300 {
							todo.status === 'completed' ? 'bg-emerald-50/50 border border-emerald-100' :
							todo.status === 'in_progress' ? 'bg-amber-50/50 border border-amber-100' :
							'bg-slate-50/40 border border-transparent'
						}">
							<span class="mt-0.5 text-xs leading-none shrink-0 {
								todo.status === 'completed' ? 'text-emerald-500' :
								todo.status === 'in_progress' ? 'text-amber-500 animate-pulse' :
								'text-slate-400'
							}">
								{#if todo.status === 'completed'}
									✓
								{:else if todo.status === 'in_progress'}
									◉
								{:else}
									○
								{/if}
							</span>
							<span class="text-[11px] leading-relaxed {
								todo.status === 'completed' ? 'text-emerald-700 line-through opacity-70' :
								todo.status === 'in_progress' ? 'text-amber-700 font-medium' :
								'text-muted-foreground'
							}">
								{todo.name}
							</span>
						</div>
					{/each}
					<div class="h-1 w-full overflow-hidden rounded-full bg-muted/60 mt-1">
						<div
							class="h-full rounded-full transition-all duration-500 {agent.status === 'complete' ? 'bg-emerald-400' : agent.status === 'error' ? 'bg-rose-400' : 'bg-primary/60'}"
							style="width: {agent.progress.percent}%"
						></div>
					</div>
				</div>
			{:else if agent.status !== 'idle'}
				<!-- No todos yet — show planning indicator -->
				<div class="flex items-center gap-2 text-[11px] text-muted-foreground/50 py-1">
					<span class="relative flex h-2 w-2">
						<span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-40"></span>
						<span class="relative inline-flex h-2 w-2 rounded-full bg-primary/60"></span>
					</span>
					<span>Planning tasks...</span>
				</div>
			{/if}

			<!-- Stats badges -->
			<div class="flex flex-wrap items-center gap-1.5 pt-1">
				{#if hasThinking}
					<Badge variant="outline" class="text-[10px] px-1.5 py-0 h-5 {agentTheme.badge}">
						<Brain class="h-2.5 w-2.5 mr-1" />
						Reasoning
					</Badge>
				{/if}
				{#if hasTools}
					<Badge variant="outline" class="text-[10px] px-1.5 py-0 h-5 {agentTheme.badge}">
						<Wrench class="h-2.5 w-2.5 mr-1" />
						{agent.toolCalls.length} tool{agent.toolCalls.length > 1 ? 's' : ''}
					</Badge>
				{/if}
				{#if hasText}
					<Badge variant="outline" class="text-[10px] px-1.5 py-0 h-5 {agentTheme.badge}">
						<MessageSquare class="h-2.5 w-2.5 mr-1" />
						Output
					</Badge>
				{/if}
				{#if agent.status === 'idle'}
					<Badge variant="outline" class="text-[10px] px-1.5 py-0 h-5 {agentTheme.badge}">
						<Sparkles class="h-2.5 w-2.5 mr-1" />
						Waiting
					</Badge>
				{/if}
			</div>
		</CardContent>
	</Card>
</button>
