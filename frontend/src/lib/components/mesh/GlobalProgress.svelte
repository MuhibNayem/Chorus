<script lang="ts">
	import type { AgentStream } from '$lib/agent-registry.svelte';
	import { Loader2, CheckCircle2, AlertCircle } from 'lucide-svelte';
	import { Card, CardContent } from '$lib/components/ui/card';

	let {
		agents,
		isRunning,
		hasError
	}: {
		agents: AgentStream[];
		isRunning: boolean;
		hasError: boolean;
	} = $props();

	const agentProgresses = $derived(
		agents.map(a => ({
			id: a.id,
			name: a.name,
			percent: a.progress.percent,
			completed: a.progress.completed,
			total: a.progress.total,
			status: a.status,
			hasDynamicTodos: a.hasDynamicTodos,
			toolCallCount: a.toolCallCount
		}))
	);

	const completedCount = $derived(agents.filter(a => a.status === 'complete').length);
	const errorCount = $derived(agents.filter(a => a.status === 'error').length);
	const totalCount = $derived(agents.length);
	const isComplete = $derived(completedCount === totalCount && totalCount > 0);
	const hasAnyError = $derived(hasError || errorCount > 0);

	const phaseColors: Record<string, string> = {
		'agent-rootdep': 'bg-violet-400',
		'agent-backend': 'bg-sky-400',
		'agent-frontend': 'bg-amber-400',
		'agent-devops': 'bg-emerald-400',
		'agent-packager': 'bg-pink-400',
	};
</script>

{#if isRunning || hasAnyError || (isComplete && totalCount > 0)}
	<Card class="rounded-3xl ring-0 border-0 bg-gradient-to-br from-white/70 to-white/50 backdrop-blur-xl overflow-hidden shadow-[0_4px_20px_rgba(0,0,0,0.06)]">
		<CardContent class="p-5">
			<!-- Header row -->
			<div class="flex items-center gap-4 mb-5">
				<div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl shadow-md {
					hasAnyError ? 'bg-gradient-to-br from-rose-400 to-red-500' :
					isComplete ? 'bg-gradient-to-br from-emerald-400 to-green-500' :
					'bg-gradient-to-br from-violet-500 to-sky-500'
				}">
					{#if hasAnyError}
						<AlertCircle class="h-5 w-5 text-white"></AlertCircle>
					{:else if isComplete}
						<CheckCircle2 class="h-5 w-5 text-white"></CheckCircle2>
					{:else}
						<Loader2 class="h-5 w-5 animate-spin text-white"></Loader2>
					{/if}
				</div>
				<div class="flex-1 min-w-0">
					<div class="flex items-center justify-between mb-1">
						<span class="text-sm font-bold tracking-tight">
							{#if hasAnyError}
								Task Failed
							{:else if isComplete}
								All Agents Complete
							{:else}
								Swarm Active
							{/if}
						</span>
					</div>
					<p class="text-[11px] text-muted-foreground/60">
						{#if hasAnyError}
							{errorCount} agent{errorCount > 1 ? 's' : ''} reported an error
						{:else}
							{completedCount}/{totalCount} agents finished
						{/if}
					</p>
				</div>
			</div>

			<!-- Per-agent progress bars -->
			<div class="grid grid-cols-2 md:grid-cols-5 gap-4">
				{#each agentProgresses as ap (ap.id)}
					<div class="flex flex-col gap-1.5 p-3 rounded-xl bg-white/40 border border-white/50 shadow-sm relative overflow-hidden">
						<!-- Background highlight for active/complete state -->
						{#if ap.status === 'working' || ap.status === 'thinking'}
							<div class="absolute inset-0 bg-primary/5 animate-pulse pointer-events-none"></div>
						{/if}
						
						<div class="flex items-center justify-between z-10">
							<span class="text-[11px] font-bold text-foreground/80 truncate pr-2">{ap.name}</span>
							{#if ap.status === 'complete'}
								<CheckCircle2 class="h-3 w-3 text-emerald-500 shrink-0" />
							{:else if ap.status === 'error'}
								<AlertCircle class="h-3 w-3 text-rose-500 shrink-0" />
							{:else if ap.status !== 'idle'}
								<Loader2 class="h-3 w-3 animate-spin text-primary shrink-0" />
							{/if}
						</div>
						
						<div class="h-1.5 w-full overflow-hidden rounded-full bg-black/5 z-10 my-1">
							<div
								class="h-full rounded-full transition-all duration-500 ease-out {ap.status === 'complete' ? 'bg-emerald-400' : ap.status === 'error' ? 'bg-rose-400' : phaseColors[ap.id] || 'bg-primary'}"
								style="width: {ap.percent}%"
							></div>
						</div>
						
						<div class="flex items-center justify-between z-10">
							<span class="text-[9px] font-medium text-muted-foreground/60 uppercase tracking-wider">
								{#if ap.hasDynamicTodos && ap.total > 0}
									{ap.completed}/{ap.total} Tasks
								{:else if ap.toolCallCount > 0}
									{ap.toolCallCount} Tools
								{:else if ap.status === 'idle'}
									Waiting
								{:else}
									Planning
								{/if}
							</span>
							<span class="text-[10px] font-bold text-foreground/70">{ap.percent}%</span>
						</div>
					</div>
				{/each}
			</div>
		</CardContent>
	</Card>
{/if}
