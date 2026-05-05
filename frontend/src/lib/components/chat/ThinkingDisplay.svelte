<script lang="ts">
	import { cn } from '$lib/utils';
	import { Badge } from '$lib/components/ui/badge';
	import { Brain, ChevronDown, ChevronRight } from 'lucide-svelte';

	let { thinking, agentName = 'Agent' }: { thinking: string; agentName?: string } = $props();

	let expanded = $state(true);
</script>

<div class="rounded-lg border bg-muted/50">
	<button
		type="button"
		onclick={() => (expanded = !expanded)}
		class="flex w-full items-center gap-2 p-3 text-left"
	>
		{#if expanded}
			<ChevronDown class="h-4 w-4 shrink-0 text-muted-foreground" />
		{:else}
			<ChevronRight class="h-4 w-4 shrink-0 text-muted-foreground" />
		{/if}
		<Brain class="h-4 w-4 shrink-0 text-purple-500" />
		<span class="text-sm font-medium">{agentName} is thinking...</span>
	</button>

	{#if expanded}
		<div class="border-t px-3 pb-3 pt-2">
			<div class="prose prose-sm dark:prose-invert max-w-none">
				<p class="whitespace-pre-wrap text-sm text-muted-foreground">{thinking}</p>
			</div>
		</div>
	{/if}
</div>
