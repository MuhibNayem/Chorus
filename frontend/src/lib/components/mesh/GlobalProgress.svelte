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

	const overallPercent = $derived(
		agents.length > 0
			? Math.round(agentProgresses.reduce((sum, a) => sum + a.percent, 0) / agents.length)
			: 0
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

	const barGradient = $derived(
		hasAnyError ? 'from-rose-400 to-red-500' :
		isComplete ? 'from-emerald-400 to-green-500' :
		'from-violet-500 via-sky-500 to-emerald-500'
	);
</script>

{#if isRunning || overallPercent > 0 || hasAnyError}
	<Card class="rounded-3xl ring-0 border-0 bg-gradient-to-br from-white/70 to-white/50 backdrop-blur-xl overflow-hidden shadow-[0_4px_20px_rgba(0,0,0,0.06)]">
		<CardContent class="p-5">
			<!-- Header row -->
			<div class="flex items-center gap-4 mb-4">
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
								Error Occurred
							{:else if isComplete}
								All Agents Complete!
							{:else}
								Swarm Working...
							{/if}
						</span>
						<span class="text-xs font-mono text-muted-foreground/70 ml-2">{overallPercent}%</span>
					</div>
					<p class="text-[11px] text-muted-foreground/60">
						{#if hasAnyError}
							{errorCount} agent{errorCount > 1 ? 's' : ''} failed
						{:else}
							{completedCount}/{totalCount} agents finished
						{/if}
					</p>
				</div>
			</div>

			<!-- Overall progress bar -->
			<div class="h-2 w-full overflow-hidden rounded-full bg-white/60 mb-5">
				<div
					class="h-full rounded-full bg-gradient-to-r {barGradient} transition-all duration-700 ease-out"
					style="width: {overallPercent}%"
				></div>
			</div>

			<!-- Per-agent progress bars — task based -->
			<div class="grid grid-cols-5 gap-3">
				{#each agentProgresses as ap (ap.id)}
					<div class="space-y-1.5">
						<div class="flex items-center justify-between">
							<span class="text-[10px] font-semibold text-muted-foreground/80 truncate">{ap.name.split(' ')[0]}</span>
						</div>
						<div class="h-1.5 w-full overflow-hidden rounded-full bg-white/60">
							<div
								class="h-full rounded-full transition-all duration-500 ease-out {ap.status === 'complete' ? 'bg-emerald-400' : ap.status === 'error' ? 'bg-rose-400' : phaseColors[ap.id] || 'bg-primary'}"
								style="width: {ap.percent}%"
							></div>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-[9px] font-mono text-muted-foreground/50">
								{#if ap.hasDynamicTodos && ap.total > 0}
									{ap.completed}/{ap.total} tasks
								{:else if ap.toolCallCount > 0}
									{ap.toolCallCount} tools
								{:else if ap.status !== 'idle'}
									Planning...
								{:else}
									—
								{/if}
							</span>
							<span class="text-[9px] font-mono text-muted-foreground/50">{ap.percent}%</span>
						</div>
					</div>
				{/each}
			</div>
		</CardContent>
	</Card>
{/if}
