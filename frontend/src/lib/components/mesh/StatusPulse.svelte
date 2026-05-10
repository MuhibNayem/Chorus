<script lang="ts">
	import type { AgentStatus } from '$lib/types';

	let { status, size = 'md' }: { status: AgentStatus; size?: 'sm' | 'md' | 'lg' } = $props();

	const sizeClasses = {
		sm: 'h-2 w-2',
		md: 'h-2.5 w-2.5',
		lg: 'h-3 w-3'
	};

	const config = $derived(
		status === 'thinking'
			? { color: 'bg-amber-400', glow: 'shadow-amber-400/50', animate: 'animate-ping', label: 'Thinking' }
			: status === 'working'
				? { color: 'bg-sky-400', glow: 'shadow-sky-400/50', animate: 'animate-pulse', label: 'Working' }
				: status === 'complete'
					? { color: 'bg-emerald-400', glow: 'shadow-emerald-400/50', animate: '', label: 'Complete' }
					: status === 'error'
						? { color: 'bg-rose-400', glow: 'shadow-rose-400/50', animate: 'animate-pulse', label: 'Error' }
						: status === 'paused'
							? { color: 'bg-amber-500', glow: 'shadow-amber-500/50', animate: 'animate-pulse', label: 'Paused' }
							: status === 'stopped'
								? { color: 'bg-slate-400', glow: 'shadow-slate-400/50', animate: '', label: 'Stopped' }
								: { color: 'bg-slate-400', glow: 'shadow-slate-400/50', animate: '', label: 'Idle' }
	);
</script>

<div class="flex items-center gap-2">
	<span class="relative flex {sizeClasses[size]}">
		{#if config.animate}
			<span
				class="absolute inline-flex h-full w-full rounded-full {config.color} opacity-60 {config.animate}"
			></span>
		{/if}
		<span
			class="relative inline-flex rounded-full {sizeClasses[size]} {config.color} {config.glow} shadow-[0_0_6px]"
		></span>
	</span>
	{#if size === 'lg'}
		<span class="text-xs font-medium text-muted-foreground/80">{config.label}</span>
	{/if}
</div>
