<script lang="ts">
	import { cn } from '$lib/utils';

	let {
		percent = 0,
		message = '',
		phase = ''
	}: { percent?: number; message?: string; phase?: string } = $props();

	const phaseLabels: Record<string, string> = {
		parsing: 'Parsing requirements',
		planning: 'Planning architecture',
		generating: 'Generating code',
		building: 'Building project',
		packaging: 'Creating distribution',
		complete: 'Complete'
	};

	const phaseColors: Record<string, string> = {
		parsing: 'bg-blue-500',
		planning: 'bg-purple-500',
		generating: 'bg-orange-500',
		building: 'bg-yellow-500',
		packaging: 'bg-green-500',
		complete: 'bg-green-600'
	};

	const currentPhase = $derived(phase || 'generating');
	const color = $derived(phaseColors[currentPhase] || 'bg-blue-500');
	const label = $derived(phaseLabels[currentPhase] || message || 'Working...');
</script>

<div class="space-y-2">
	<div class="flex items-center justify-between text-sm">
		<span class="text-muted-foreground">{label}</span>
		<span class="font-medium">{percent}%</span>
	</div>
	<div class="h-2 w-full overflow-hidden rounded-full bg-muted">
		<div
			class={cn('h-full rounded-full transition-all duration-500', color)}
			style="width: {percent}%"
		></div>
	</div>
</div>
