<script lang="ts">
	import { cn } from '$lib/utils';
	import type { ChatMessage } from '$lib/types';
	import { Badge } from '$lib/components/ui/badge';
	import MarkdownContent from './MarkdownContent.svelte';
	import { Sparkles, UserRound } from 'lucide-svelte';

	let { message }: { message: ChatMessage } = $props();

	const isUser = $derived(message.role === 'user');

	function getAssistantName(content: string): string {
		const match = content.match(/^\[([^\]]+)\]:\s*/);
		return match?.[1] || 'Chorus Agent';
	}

	function getDisplayContent(content: string): string {
		return content.replace(/^\[[^\]]+\]:\s*/, '');
	}

	const speakerName = $derived(isUser ? 'You' : getAssistantName(message.content));
	const displayContent = $derived(isUser ? message.content : getDisplayContent(message.content));
</script>

<div class={cn('group flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
	<div
		class={cn(
			'relative flex h-10 w-10 shrink-0 select-none items-center justify-center overflow-hidden rounded-2xl border shadow-[0_10px_24px_rgba(15,23,42,0.10)]',
			isUser
				? 'border-cyan-200/70 bg-[linear-gradient(145deg,rgba(14,165,233,0.86),rgba(20,184,166,0.78))] text-white'
				: 'border-white/70 bg-[linear-gradient(145deg,rgba(236,253,245,0.92),rgba(224,242,254,0.88)_48%,rgba(255,255,255,0.78))]'
		)}
	>
		{#if isUser}
			<span class="absolute inset-x-2 top-1 h-px rounded-full bg-white/70 blur-[1px]"></span>
			<UserRound class="relative z-10 h-4.5 w-4.5" />
		{:else}
			<span class="absolute inset-[2px] rounded-[0.85rem] bg-white/35 backdrop-blur-xl"></span>
			<svg
				class="relative z-10 h-6 w-6"
				viewBox="0 0 28 28"
				fill="none"
				aria-hidden="true"
			>
				<path
					d="M14 4.2C18.9 4.2 22.8 8.1 22.8 13C22.8 17.9 18.9 21.8 14 21.8C9.1 21.8 5.2 17.9 5.2 13C5.2 8.1 9.1 4.2 14 4.2Z"
					fill="url(#agent-core)"
				/>
				<path
					d="M9.2 15.6C11.9 12.9 15.7 11.6 19.8 11.9"
					stroke="rgba(14,116,144,0.78)"
					stroke-width="1.7"
					stroke-linecap="round"
				/>
				<path
					d="M9.4 10.5C12.6 13 15.3 15.6 17.5 18.4"
					stroke="rgba(20,184,166,0.86)"
					stroke-width="1.7"
					stroke-linecap="round"
				/>
				<circle cx="9.4" cy="10.5" r="2.1" fill="#0ea5e9" />
				<circle cx="19.7" cy="11.9" r="2.1" fill="#14b8a6" />
				<circle cx="17.5" cy="18.4" r="2.1" fill="#f59e0b" />
				<defs>
					<linearGradient id="agent-core" x1="7" x2="22" y1="5" y2="22" gradientUnits="userSpaceOnUse">
						<stop stop-color="#f8fafc" />
						<stop offset="0.48" stop-color="#dff7ef" />
						<stop offset="1" stop-color="#bae6fd" />
					</linearGradient>
				</defs>
			</svg>
			<span class="absolute inset-x-2 top-1 h-px rounded-full bg-white/80 blur-[1px]"></span>
		{/if}
	</div>

	<div class={cn('flex max-w-[82%] flex-col gap-2', isUser ? 'items-end' : 'items-start')}>
		<div class={cn('flex items-center gap-1.5 px-1 text-[10px] font-semibold uppercase tracking-[0.14em]', isUser ? 'text-cyan-700/65' : 'text-teal-700/70')}>
			{#if !isUser}
				<Sparkles class="h-3 w-3 text-amber-500/80" />
			{/if}
			<span>{speakerName}</span>
		</div>

		<div
			class={cn(
				'relative overflow-hidden rounded-2xl border px-4 py-3 text-sm leading-6 shadow-[0_14px_32px_rgba(15,23,42,0.08)] backdrop-blur-xl',
				isUser
					? 'rounded-tr-md border-sky-200/70 bg-[linear-gradient(145deg,rgba(255,255,255,0.78),rgba(239,246,255,0.68)_52%,rgba(224,242,254,0.58))] text-slate-800 shadow-[0_14px_34px_rgba(56,189,248,0.10)]'
					: 'rounded-tl-md border-white/70 bg-[linear-gradient(145deg,rgba(255,255,255,0.88),rgba(240,253,250,0.78)_48%,rgba(239,246,255,0.72))] text-slate-800'
			)}
		>
			<span class={cn(
				'pointer-events-none absolute inset-x-4 top-1 h-px rounded-full blur-[1px]',
				isUser ? 'bg-white/90' : 'bg-white/75'
			)}></span>
			<div class={cn(
				'relative z-10 min-w-0',
				isUser
					? 'text-slate-800 [&_a]:text-sky-700 [&_code]:bg-sky-50 [&_code]:text-sky-900 [&_pre]:border-sky-200/60 [&_pre]:bg-white/85'
					: 'text-slate-800 [&_a]:text-cyan-700 [&_code]:bg-slate-900/10 [&_pre]:border-black/10'
			)}>
				<MarkdownContent source={displayContent} />
			</div>
		</div>

		{#if message.metadata?.checkpoint_id}
			<div class="mt-1 flex flex-col gap-2 rounded-2xl border border-teal-200/60 bg-white/65 p-3 shadow-sm backdrop-blur-xl">
				<div class="flex items-center gap-2">
					<div class="h-2 w-2 rounded-full bg-teal-500 animate-pulse"></div>
					<span class="text-[10px] font-bold uppercase tracking-wider text-teal-700/70">Checkpoint Created</span>
				</div>
				<p class="text-[11px] text-muted-foreground leading-relaxed">
					Workspace state has been archived. You can roll back to this exact version at any time.
				</p>
				<button
					class="w-full rounded-xl bg-white/70 py-1.5 text-[10px] font-semibold text-teal-700 transition-all hover:bg-white hover:shadow-sm active:scale-[0.98] border border-teal-200/60"
					onclick={async () => {
						const activeProjectId = localStorage.getItem('chorus.activeProjectId');
						if (!activeProjectId) return;
						
						if (confirm('Are you sure you want to restore this checkpoint? Current unsaved changes will be lost.')) {
							try {
								const res = await fetch(`/api/projects/${activeProjectId}/restore/${message.metadata?.checkpoint_id}`, {
									method: 'POST'
								});
								if (res.ok) {
									alert('Checkpoint restored successfully! Refreshing page...');
									window.location.reload();
								} else {
									const data = await res.json();
									alert(`Restore failed: ${data.error}`);
								}
							} catch (e) {
								console.error('Restore error:', e);
							}
						}
					}}
				>
					Restore this version
				</button>
			</div>
		{/if}

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
