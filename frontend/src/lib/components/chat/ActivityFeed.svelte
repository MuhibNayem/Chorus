<script lang="ts">
	import { cn } from '$lib/utils';
	import type { AgentActivity } from '$lib/types';
	import { Badge } from '$lib/components/ui/badge';
	import { Bot, Loader2, CheckCircle2, XCircle, Clock } from 'lucide-svelte';

	let { activities }: { activities: AgentActivity[] } = $props();

	function getStatusColor(status: AgentActivity['status']) {
		switch (status) {
			case 'thinking':
				return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20';
			case 'working':
				return 'bg-blue-500/10 text-blue-600 border-blue-500/20';
			case 'complete':
				return 'bg-green-500/10 text-green-600 border-green-500/20';
			case 'error':
				return 'bg-red-500/10 text-red-600 border-red-500/20';
		}
	}
</script>

<div class="flex flex-col gap-2">
	{#each activities as activity}
		{@const IconComponent = activity.status === 'thinking' ? Clock : activity.status === 'working' ? Loader2 : activity.status === 'complete' ? CheckCircle2 : XCircle}
		<div
			class={cn(
				'flex items-center gap-2 rounded-lg border p-3 text-sm',
				getStatusColor(activity.status)
			)}
		>
			<IconComponent class="h-4 w-4 shrink-0" />
			<span class="font-medium">{activity.agent_name}:</span>
			<span class="text-muted-foreground">{activity.action}</span>
		</div>
	{/each}
</div>
