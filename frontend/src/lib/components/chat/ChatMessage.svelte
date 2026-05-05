<script lang="ts">
	import { cn } from '$lib/utils';
	import type { ChatMessage } from '$lib/types';
	import { Badge } from '$lib/components/ui/badge';
	import { Bot, User } from 'lucide-svelte';

	let { message }: { message: ChatMessage } = $props();

	const isUser = $derived(message.role === 'user');
</script>

<div class={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
	<div
		class={cn(
			'flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border',
			isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
		)}
	>
		{#if isUser}
			<User class="h-4 w-4" />
		{:else}
			<Bot class="h-4 w-4" />
		{/if}
	</div>

	<div class={cn('flex max-w-[80%] flex-col gap-2', isUser ? 'items-end' : 'items-start')}>
		<div
			class={cn(
				'rounded-lg px-4 py-2 text-sm',
				isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
			)}
		>
			{message.content}
		</div>

		{#if message.events && message.events.length > 0}
			<div class="flex flex-wrap gap-1">
				{#each message.events as event}
					<Badge variant="outline" class="text-xs">
						{event.type}
					</Badge>
				{/each}
			</div>
		{/if}
	</div>
</div>
