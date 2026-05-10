<script lang="ts">
	import type { ClaimInfo } from '$lib/types';
	import { Badge } from '$lib/components/ui/badge';
	import { Card, CardContent, CardHeader } from '$lib/components/ui/card';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import Shield from '@lucide/svelte/icons/shield';
	import ShieldAlert from '@lucide/svelte/icons/shield-alert';
	import ShieldCheck from '@lucide/svelte/icons/shield-check';
	import ShieldX from '@lucide/svelte/icons/shield-x';
	import FileText from '@lucide/svelte/icons/file-text';
	import AlertCircle from '@lucide/svelte/icons/alert-circle';
	import Scroll from '@lucide/svelte/icons/scroll';

	let { claims }: { claims: ClaimInfo[] } = $props();

	const statusConfig: Record<string, { label: string; icon: typeof Shield; color: string; bg: string; border: string }> = {
		valid: {
			label: 'Valid',
			icon: ShieldCheck,
			color: 'text-emerald-500',
			bg: 'bg-emerald-500/10',
			border: 'border-emerald-500/20'
		},
		claimed: {
			label: 'Claimed',
			icon: Shield,
			color: 'text-sky-500',
			bg: 'bg-sky-500/10',
			border: 'border-sky-500/20'
		},
		invalid: {
			label: 'Invalid',
			icon: ShieldX,
			color: 'text-rose-500',
			bg: 'bg-rose-500/10',
			border: 'border-rose-500/20'
		},
		stale: {
			label: 'Stale',
			icon: ShieldAlert,
			color: 'text-amber-500',
			bg: 'bg-amber-500/10',
			border: 'border-amber-500/20'
		},
		revoked: {
			label: 'Revoked',
			icon: ShieldX,
			color: 'text-slate-500',
			bg: 'bg-slate-500/10',
			border: 'border-slate-500/20'
		}
	};

	function getStatusConfig(status: string) {
		return statusConfig[status] || statusConfig.claimed;
	}
</script>

<div class="space-y-3">
	{#if claims.length === 0}
		<div class="flex flex-col items-center justify-center py-12 text-muted-foreground/50">
			<Shield class="h-8 w-8 mb-3 opacity-40" />
			<p class="text-sm">No claims recorded</p>
			<p class="text-xs mt-1">Claim status will appear here as the agent publishes evidence</p>
		</div>
	{:else}
		<div class="flex items-center gap-2 mb-1">
			<Scroll class="h-4 w-4 text-teal-600" />
			<span class="text-sm font-bold text-teal-700">Readiness Claims</span>
			<Badge variant="secondary" class="text-[10px] px-1.5 h-5">{claims.length}</Badge>
		</div>
		<p class="text-[11px] text-muted-foreground italic px-0.5">
			Evidence-backed claims track what this agent has verified.
		</p>

		{#each claims as claim (claim.claim_id || claim.claim_type)}
			{@const cfg = getStatusConfig(claim.claim_status)}
			{@const StatusIcon = cfg.icon}
			<Card class="overflow-hidden rounded-2xl {cfg.border} {cfg.bg} shadow-[0_10px_24px_rgba(15,23,42,0.06)] backdrop-blur-md">
				<CardContent class="p-3.5">
					<div class="flex items-start gap-3">
						<div class="mt-0.5 shrink-0">
							<StatusIcon class="h-5 w-5 {cfg.color}" />
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2 flex-wrap">
								<span class="text-xs font-bold text-foreground">{claim.claim_type}</span>
								<Badge
									variant="outline"
									class="text-[10px] px-1.5 h-5 {cfg.color} {cfg.bg} {cfg.border}"
								>
									{cfg.label}
								</Badge>
							</div>

							{#if claim.evidence_files && claim.evidence_files.length > 0}
								<div class="mt-2 flex flex-wrap gap-1.5">
									{#each claim.evidence_files as file}
										<div class="inline-flex items-center gap-1 rounded-lg border border-white/60 bg-white/50 px-2 py-1 text-[10px] text-muted-foreground shadow-sm">
											<FileText class="h-3 w-3" />
											<span class="truncate max-w-[180px]">{file}</span>
										</div>
									{/each}
								</div>
							{/if}

							{#if claim.validation_errors && claim.validation_errors.length > 0}
								<div class="mt-2 space-y-1">
									{#each claim.validation_errors as err}
										<div class="flex items-start gap-1.5 rounded-lg bg-rose-500/8 border border-rose-500/15 px-2.5 py-1.5">
											<AlertCircle class="h-3 w-3 text-rose-500 mt-0.5 shrink-0" />
											<span class="text-[10px] text-rose-600 leading-relaxed">{err}</span>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				</CardContent>
			</Card>
		{/each}
	{/if}
</div>
