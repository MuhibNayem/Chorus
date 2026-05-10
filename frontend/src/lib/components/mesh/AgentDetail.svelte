<script lang="ts">
	import type { AgentStream } from '$lib/agent-registry.svelte';
	import StatusPulse from './StatusPulse.svelte';
	import ClaimPanel from './ClaimPanel.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Card, CardContent, CardHeader } from '$lib/components/ui/card';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import X from '@lucide/svelte/icons/x';
	import Brain from '@lucide/svelte/icons/brain';
	import Wrench from '@lucide/svelte/icons/wrench';
	import Terminal from '@lucide/svelte/icons/terminal';
	import Clock from '@lucide/svelte/icons/clock';
	import CheckCircle2 from '@lucide/svelte/icons/check-circle-2';
	import XCircle from '@lucide/svelte/icons/x-circle';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import Copy from '@lucide/svelte/icons/copy';
	import Check from '@lucide/svelte/icons/check';
	import ListTodo from '@lucide/svelte/icons/list-todo';
	import Shield from '@lucide/svelte/icons/shield';

	let {
		agent,
		onClose
	}: {
		agent: AgentStream;
		onClose: () => void;
	} = $props();

	let activeTab = $state<'stream' | 'plan' | 'thinking' | 'tools' | 'claims'>('stream');
	let copied = $state(false);

	const statusConfig = $derived(
		agent.status === 'thinking'
			? { icon: Clock, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' }
			: agent.status === 'working'
				? { icon: Loader2, color: 'text-sky-400', bg: 'bg-sky-500/10 border-sky-500/20' }
				: agent.status === 'complete'
					? { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' }
					: agent.status === 'error'
						? { icon: XCircle, color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/20' }
						: { icon: Clock, color: 'text-slate-400', bg: 'bg-slate-500/10 border-slate-500/20' }
	);

	const StatusIcon = $derived(statusConfig.icon);

	const tabClass = (tab: string) =>
		`inline-flex items-center rounded-xl px-3 py-2 text-xs font-semibold transition-all duration-200 ${
			activeTab === tab
				? 'bg-white/75 text-slate-900 shadow-[0_10px_22px_rgba(15,23,42,0.10)] ring-1 ring-white/70'
				: 'text-muted-foreground hover:bg-white/45 hover:text-foreground'
		}`;

	function copyText(text: string) {
		navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 1500);
	}
</script>

<div class="m-4 flex h-[calc(100%-2rem)] flex-col overflow-hidden rounded-[2rem] border border-white/55 bg-[linear-gradient(145deg,rgba(255,255,255,0.72),rgba(240,253,250,0.52)_46%,rgba(239,246,255,0.48))] shadow-[0_20px_54px_rgba(15,23,42,0.12)] backdrop-blur-2xl">
	<!-- Header -->
	<div class="border-b border-white/45 px-5 py-5">
		<div class="flex items-start justify-between gap-4">
			<div class="flex min-w-0 items-center gap-3">
				<div class="relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-white/70 bg-white/65 shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_12px_26px_rgba(15,23,42,0.10)]">
					<span class="absolute inset-x-2 top-1 h-px rounded-full bg-white/80 blur-[1px]"></span>
					<StatusIcon class="relative z-10 h-5 w-5 {statusConfig.color}" />
				</div>
				<div class="min-w-0">
					<p class="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground/55">Agent Inspector</p>
					<h2 class="truncate text-base font-bold tracking-tight text-slate-900">{agent.name}</h2>
					<div class="mt-1 flex items-center gap-2">
						<StatusPulse status={agent.status} size="sm" />
						<span class="truncate text-xs text-muted-foreground">{agent.currentAction || 'Idle'}</span>
					</div>
				</div>
			</div>
			<button
				type="button"
				class="rounded-xl border border-white/50 bg-white/45 p-2 text-muted-foreground/60 shadow-sm transition-colors hover:bg-white hover:text-foreground"
				onclick={onClose}
			>
				<X class="h-4 w-4" />
			</button>
		</div>

		<div class="mt-4 grid grid-cols-3 gap-2">
			<div class="rounded-2xl border border-white/55 bg-white/45 px-3 py-2 shadow-sm">
				<p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">Events</p>
				<p class="mt-1 text-sm font-bold text-slate-900">{agent.events.length}</p>
			</div>
			<div class="rounded-2xl border border-white/55 bg-white/45 px-3 py-2 shadow-sm">
				<p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">Tools</p>
				<p class="mt-1 text-sm font-bold text-slate-900">{agent.toolCalls.length}</p>
			</div>
			<div class="rounded-2xl border border-white/55 bg-white/45 px-3 py-2 shadow-sm">
				<p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">Progress</p>
				<p class="mt-1 text-sm font-bold text-slate-900">{agent.progress.percent}%</p>
			</div>
		</div>
	</div>

	<!-- Tabs -->
	<div class="mx-5 mt-4 flex items-center gap-1.5 overflow-x-auto rounded-2xl border border-white/50 bg-white/35 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] backdrop-blur-xl">
		<button class={tabClass('stream')} onclick={() => (activeTab = 'stream')}>
			<Terminal class="inline h-3 w-3 mr-1" />
			Stream
			<Badge variant="secondary" class="ml-1 text-[10px] px-1 h-4 min-w-[18px]">{agent.events.length}</Badge>
		</button>
		<button class={tabClass('plan')} onclick={() => (activeTab = 'plan')}>
			<ListTodo class="inline h-3 w-3 mr-1" />
			Plan
			{#if agent.tasks.length > 0}
				<Badge variant="secondary" class="ml-1 text-[10px] px-1 h-4 min-w-[18px]">{agent.progress.completed}/{agent.progress.total}</Badge>
			{/if}
		</button>
		<button class={tabClass('thinking')} onclick={() => (activeTab = 'thinking')}>
			<Brain class="inline h-3 w-3 mr-1" />
			Thinking
		</button>
		<button class={tabClass('tools')} onclick={() => (activeTab = 'tools')}>
			<Wrench class="inline h-3 w-3 mr-1" />
			Tools
			<Badge variant="secondary" class="ml-1 text-[10px] px-1 h-4 min-w-[18px]">{agent.toolCalls.length}</Badge>
		</button>
	</div>

	<!-- Content -->
	<div class="flex-1 min-h-0">
		<ScrollArea class="h-full">
		<div class="p-5 space-y-3">
			{#if activeTab === 'stream'}
				{#each agent.events as event (event.id)}
					<Card class="overflow-hidden rounded-2xl border-white/60 bg-white/58 shadow-[0_10px_24px_rgba(15,23,42,0.06)] backdrop-blur-md">
						<CardContent class="p-3">
							<div class="flex gap-3">
								<span class="shrink-0 text-[10px] font-mono text-muted-foreground/50 mt-0.5">
									{new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
								</span>
								<div class="flex-1 min-w-0">
									<Badge
										variant="outline"
										class="text-[10px] px-1.5 py-0 h-5 mb-1.5 {event.type === 'error' ? 'border-rose-500/30 text-rose-400 bg-rose-500/10' : event.type === 'complete' ? 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10' : event.type === 'thinking' ? 'border-amber-500/30 text-amber-400 bg-amber-500/10' : event.type === 'tool_call' ? 'border-sky-500/30 text-sky-400 bg-sky-500/10' : 'border-border/40 text-muted-foreground bg-muted/30'}"
									>
										{event.type}
									</Badge>
									{#if event.content}
										<p class="text-xs text-foreground/80 whitespace-pre-wrap leading-relaxed">{event.content}</p>
									{/if}
									{#if event.data && Object.keys(event.data).length > 0}
										<details class="mt-2">
											<summary class="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground transition-colors">Data</summary>
											<pre class="mt-1.5 text-[10px] bg-background/60 rounded-lg p-2.5 overflow-x-auto border border-border/20">{JSON.stringify(event.data, null, 2)}</pre>
										</details>
									{/if}
								</div>
							</div>
						</CardContent>
					</Card>
				{:else}
					<div class="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
						<Terminal class="h-8 w-8 mb-3 opacity-40" />
						<p class="text-sm">No events yet</p>
						<p class="text-xs mt-1">Agent activity will stream here in real-time</p>
					</div>
				{/each}

			{:else if activeTab === 'plan'}
				{#if agent.tasks.length > 0}
					<div class="space-y-4">
					<Card class="overflow-hidden rounded-2xl border-teal-200/55 bg-white/60 shadow-[0_10px_24px_rgba(15,23,42,0.06)] backdrop-blur-md">
							<CardContent class="p-4">
								<div class="flex items-center justify-between mb-3">
									<div class="flex items-center gap-2">
										<ListTodo class="h-4 w-4 text-teal-600" />
										<span class="text-sm font-bold text-teal-700">Execution Plan</span>
									</div>
									<span class="text-xs font-mono font-bold text-teal-700">{agent.progress.percent}% Complete</span>
								</div>
								<div class="h-2 w-full overflow-hidden rounded-full bg-teal-500/10">
									<div
										class="h-full rounded-full bg-gradient-to-r from-teal-500 to-sky-500 transition-all duration-700 ease-out"
										style="width: {agent.progress.percent}%"
									></div>
								</div>
								<p class="text-[11px] text-muted-foreground mt-3 italic">
									Completed {agent.progress.completed} of {agent.progress.total} planned operations.
								</p>
							</CardContent>
						</Card>

						<div class="space-y-2 px-1">
							{#each agent.tasks as todo, i (i)}
								<div class="flex items-start gap-3 rounded-2xl p-3 border transition-all duration-300 {
									todo.status === 'completed' ? 'bg-emerald-50/30 border-emerald-100/50' :
									todo.status === 'in_progress' ? 'bg-white shadow-sm border-primary/20 scale-[1.01]' :
									'bg-muted/20 border-transparent'
								}">
									<div class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border {
										todo.status === 'completed' ? 'bg-emerald-500 border-emerald-500 text-white' :
										todo.status === 'in_progress' ? 'bg-white border-primary text-primary animate-pulse' :
										'bg-white border-muted-foreground/30 text-muted-foreground/30'
									}">
										{#if todo.status === 'completed'}
											<Check class="h-3 w-3" />
										{:else}
											<span class="text-[10px] font-bold">{i + 1}</span>
										{/if}
									</div>
									<div class="flex-1 min-w-0">
										<p class="text-sm leading-tight {
											todo.status === 'completed' ? 'text-muted-foreground/60 line-through' :
											todo.status === 'in_progress' ? 'text-foreground font-bold' :
											'text-muted-foreground/80'
										}">
											{todo.name}
										</p>
										{#if todo.status === 'in_progress'}
											<span class="text-[10px] font-bold text-primary uppercase tracking-widest mt-1 block">Active</span>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					</div>
				{:else}
					<div class="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
						<ListTodo class="h-8 w-8 mb-3 opacity-40" />
						<p class="text-sm">No plan authored yet</p>
						<p class="text-xs mt-1">The agent will broadcast its steps once work begins</p>
					</div>
				{/if}

			{:else if activeTab === 'thinking'}
				{#if agent.thinking}
					<Card class="overflow-hidden rounded-2xl border-amber-200/60 bg-amber-50/60 shadow-[0_10px_24px_rgba(15,23,42,0.06)] backdrop-blur-md">
						<CardHeader class="pb-2 pt-3 px-4">
							<div class="flex items-center justify-between">
								<div class="flex items-center gap-2">
									<Brain class="h-4 w-4 text-amber-400" />
									<span class="text-xs font-semibold text-amber-400">Reasoning Stream</span>
								</div>
								<button
									type="button"
									class="rounded-md p-1.5 text-muted-foreground/50 hover:text-foreground hover:bg-muted transition-colors"
									onclick={() => copyText(agent.thinking)}
								>
									{#if copied}
										<Check class="h-3.5 w-3.5 text-emerald-400" />
									{:else}
										<Copy class="h-3.5 w-3.5" />
									{/if}
								</button>
							</div>
						</CardHeader>
						<CardContent class="px-4 pb-4">
							<div class="prose prose-sm dark:prose-invert max-w-none">
								<p class="whitespace-pre-wrap text-sm text-foreground/80 leading-relaxed font-mono">{agent.thinking}</p>
							</div>
						</CardContent>
					</Card>
				{:else}
					<div class="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
						<Brain class="h-8 w-8 mb-3 opacity-40" />
						<p class="text-sm">No thinking recorded yet</p>
					</div>
				{/if}

			{:else if activeTab === 'tools'}
				{#each agent.toolCalls as tool (tool.id)}
					<Card class="overflow-hidden rounded-2xl border-sky-200/60 bg-sky-50/60 shadow-[0_10px_24px_rgba(15,23,42,0.06)] backdrop-blur-md">
						<CardContent class="p-3">
							<div class="flex items-center gap-2 mb-2">
								<Wrench class="h-3.5 w-3.5 text-sky-400" />
								<span class="text-xs font-semibold text-sky-400">{tool.type}</span>
								<span class="text-[10px] text-muted-foreground/50 ml-auto font-mono">
									{new Date(tool.timestamp).toLocaleTimeString()}
								</span>
							</div>
							{#if tool.content}
								<p class="text-xs text-foreground/80">{tool.content}</p>
							{/if}
							{#if tool.data}
								<pre class="mt-2 text-[10px] bg-background/60 rounded-lg p-2.5 overflow-x-auto border border-border/20">{JSON.stringify(tool.data, null, 2)}</pre>
							{/if}
						</CardContent>
					</Card>
				{:else}
					<div class="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
						<Wrench class="h-8 w-8 mb-3 opacity-40" />
						<p class="text-sm">No tool calls yet</p>
					</div>
				{/each}
			{/if}
		</div>
	</ScrollArea>
	</div>
</div>
