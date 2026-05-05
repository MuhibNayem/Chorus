<script lang="ts">
	import type { AgentStream } from '$lib/agent-registry.svelte';
	import StatusPulse from './StatusPulse.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Card, CardContent, CardHeader } from '$lib/components/ui/card';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import {
		X,
		Brain,
		Wrench,
		MessageSquare,
		Terminal,
		Clock,
		CheckCircle2,
		XCircle,
		Loader2,
		Copy,
		Check
	} from 'lucide-svelte';

	let {
		agent,
		onClose
	}: {
		agent: AgentStream;
		onClose: () => void;
	} = $props();

	let activeTab = $state<'stream' | 'thinking' | 'tools' | 'output'>('stream');
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
		`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
			activeTab === tab
				? 'bg-primary text-primary-foreground shadow-sm'
				: 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
		}`;

	function copyText(text: string) {
		navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 1500);
	}
</script>

<div class="flex h-[calc(100%-2rem)] m-4 flex-col rounded-[2.5rem] border border-white/50 bg-white/40 shadow-[0_8px_30px_rgb(0,0,0,0.04)] backdrop-blur-xl overflow-hidden">
	<!-- Header -->
	<div class="flex items-center justify-between border-b border-border/40 px-5 py-4">
		<div class="flex items-center gap-3">
			<div class="flex h-10 w-10 items-center justify-center rounded-xl {statusConfig.bg}">
				<StatusIcon class="h-5 w-5 {statusConfig.color}" />
			</div>
			<div>
				<h2 class="text-sm font-bold tracking-tight">{agent.name}</h2>
				<div class="flex items-center gap-2 mt-0.5">
					<StatusPulse status={agent.status} size="sm" />
					<span class="text-xs text-muted-foreground">{agent.currentAction || 'Idle'}</span>
				</div>
			</div>
		</div>
		<button
			type="button"
			class="rounded-lg p-2 text-muted-foreground/60 hover:bg-muted hover:text-foreground transition-colors"
			onclick={onClose}
		>
			<X class="h-4 w-4" />
		</button>
	</div>

	<div class="h-px bg-border/40"></div>
	<!-- Tabs -->
	<div class="flex items-center gap-1.5 px-5 py-2.5">
		<button class={tabClass('stream')} onclick={() => (activeTab = 'stream')}>
			<Terminal class="inline h-3 w-3 mr-1" />
			Stream
			<Badge variant="secondary" class="ml-1 text-[10px] px-1 h-4 min-w-[18px]">{agent.events.length}</Badge>
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
		<button class={tabClass('output')} onclick={() => (activeTab = 'output')}>
			<MessageSquare class="inline h-3 w-3 mr-1" />
			Output
		</button>
	</div>

	<div class="h-px bg-border/40"></div>
	<!-- Content -->
	<div class="flex-1 min-h-0">
		<ScrollArea class="h-full">
		<div class="p-5 space-y-3">
			{#if activeTab === 'stream'}
				{#each agent.events as event (event.id)}
					<Card class="rounded-3xl border-white/60 bg-white/50 backdrop-blur-md overflow-hidden shadow-sm">
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

			{:else if activeTab === 'thinking'}
				{#if agent.thinking}
					<Card class="rounded-3xl border-amber-300/50 bg-amber-50/50 backdrop-blur-md overflow-hidden shadow-sm">
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
					<Card class="rounded-3xl border-sky-300/50 bg-sky-50/50 backdrop-blur-md overflow-hidden shadow-sm">
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

			{:else if activeTab === 'output'}
				{#if agent.textOutput}
					<Card class="rounded-3xl border-emerald-300/50 bg-emerald-50/50 backdrop-blur-md overflow-hidden shadow-sm">
						<CardHeader class="pb-2 pt-3 px-4">
							<div class="flex items-center justify-between">
								<div class="flex items-center gap-2">
									<MessageSquare class="h-4 w-4 text-emerald-400" />
									<span class="text-xs font-semibold text-emerald-400">Text Output</span>
								</div>
								<button
									type="button"
									class="rounded-md p-1.5 text-muted-foreground/50 hover:text-foreground hover:bg-muted transition-colors"
									onclick={() => copyText(agent.textOutput)}
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
								<p class="whitespace-pre-wrap text-sm text-foreground/90 leading-relaxed">{agent.textOutput}</p>
							</div>
						</CardContent>
					</Card>
				{:else}
					<div class="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
						<MessageSquare class="h-8 w-8 mb-3 opacity-40" />
						<p class="text-sm">No text output yet</p>
					</div>
				{/if}
			{/if}
		</div>
	</ScrollArea>
	</div>
</div>
