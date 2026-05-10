<script lang="ts">
	import type {
		AgentStream,
		AgentStreamEvent,
		AgentEventType,
	} from "$lib/agent-registry.svelte";
	import Brain from '@lucide/svelte/icons/brain';
	import CheckCircle2 from '@lucide/svelte/icons/check-circle-2';
	import Clock3 from '@lucide/svelte/icons/clock-3';
	import FileCode2 from '@lucide/svelte/icons/file-code-2';
	import FileSearch from '@lucide/svelte/icons/file-search';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import TerminalSquare from '@lucide/svelte/icons/terminal-square';
	import Wrench from '@lucide/svelte/icons/wrench';
	import XCircle from '@lucide/svelte/icons/x-circle';

	let {
		agents,
		isStreaming = false,
		hasSpec = false,
		statusLabel = "Waiting for plan generation",
	}: {
		agents: AgentStream[];
		isStreaming?: boolean;
		hasSpec?: boolean;
		statusLabel?: string;
	} = $props();

	const visibleAgents = $derived(
		agents.filter((agent) => agent.id === "agent-rootdep" || agent.events.length > 0),
	);
	const primaryAgent = $derived(
		visibleAgents.find((agent) => agent.id === "agent-rootdep") ??
			visibleAgents[0] ??
			null,
	);
	const timelineEvents = $derived.by(() => {
		const items: Array<
			AgentStreamEvent & { agentName: string; eventKey: string }
		> = [];

		for (const agent of visibleAgents) {
			for (const event of agent.events) {
				items.push({
					...event,
					agentName: agent.name,
					eventKey: `${agent.id}-${event.id}`,
				});
			}
		}

		return items
			.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
			.slice(0, 18);
	});
	const recentToolCalls = $derived.by(() => {
		const toolEvents = primaryAgent?.toolCalls ?? [];
		return [...toolEvents].slice(-6).reverse();
	});
	const reasoningPreview = $derived(
		primaryAgent?.thinking?.trim()
			? primaryAgent.thinking.trim()
			: "Reasoning summaries will appear here while the planner explores the codebase, lists files, searches context, and writes SPEC.md.",
	);
	const eventCount = $derived(
		visibleAgents.reduce((sum, agent) => sum + agent.events.length, 0),
	);
	const toolCount = $derived(
		visibleAgents.reduce((sum, agent) => sum + agent.toolCalls.length, 0),
	);

	function formatTimestamp(timestamp: number | string) {
		return new Date(timestamp).toLocaleTimeString([], {
			hour: "2-digit",
			minute: "2-digit",
			second: "2-digit",
		});
	}

	function getEventMeta(type: AgentEventType) {
		switch (type) {
			case "thinking":
			case "reasoning":
				return {
					label: "Reasoning",
					icon: Brain,
					className:
						"border-amber-200/65 bg-amber-50/80 text-amber-700 shadow-[0_0_20px_rgba(245,158,11,0.12)]",
				};
			case "tool_start":
			case "tool_call":
			case "tool_result":
				return {
					label: "Tool",
					icon: Wrench,
					className:
						"border-sky-200/70 bg-sky-50/80 text-sky-700 shadow-[0_0_20px_rgba(14,165,233,0.12)]",
				};
			case "context_built":
			case "context_compacted":
				return {
					label: "Context",
					icon: FileSearch,
					className:
						"border-violet-200/70 bg-violet-50/80 text-violet-700 shadow-[0_0_20px_rgba(139,92,246,0.12)]",
				};
			case "progress":
			case "state":
				return {
					label: "Progress",
					icon: Loader2,
					className:
						"border-emerald-200/70 bg-emerald-50/80 text-emerald-700 shadow-[0_0_20px_rgba(16,185,129,0.12)]",
				};
			case "complete":
			case "PlanReady":
				return {
					label: "Done",
					icon: CheckCircle2,
					className:
						"border-emerald-200/70 bg-emerald-50/80 text-emerald-700 shadow-[0_0_20px_rgba(16,185,129,0.12)]",
				};
			case "error":
			case "RunError":
				return {
					label: "Error",
					icon: XCircle,
					className:
						"border-rose-200/70 bg-rose-50/80 text-rose-700 shadow-[0_0_20px_rgba(244,63,94,0.12)]",
				};
			default:
				return {
					label: "Event",
					icon: TerminalSquare,
					className:
						"border-slate-200/70 bg-white/80 text-slate-700 shadow-[0_0_20px_rgba(15,23,42,0.06)]",
				};
		}
	}
</script>

<div class="rounded-[2.5rem] border border-cyan-200/45 bg-[linear-gradient(145deg,rgba(255,255,255,0.9),rgba(239,246,255,0.72))] p-4 shadow-[0_24px_70px_rgba(15,23,42,0.12)] backdrop-blur-2xl">
	<div class="flex flex-wrap items-start justify-between gap-4 border-b border-white/55 pb-4">
		<div class="max-w-3xl">
			<div class="flex items-center gap-3">
				<div class="flex h-11 w-11 items-center justify-center rounded-2xl border border-cyan-200/60 bg-cyan-50/80 text-cyan-700 shadow-[0_0_20px_rgba(34,211,238,0.18)]">
					<Sparkles class="h-5 w-5" />
				</div>
				<div>
					<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-700/70">
						Live Planning Trace
					</p>
					<h3 class="text-xl font-semibold tracking-tight text-slate-900">
						Root architect activity
					</h3>
				</div>
			</div>
			<p class="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
				This stream shows how the planning agent is building context, invoking tools,
				reasoning through the request, and preparing <code>SPEC.md</code>.
			</p>
		</div>
		<div class="flex flex-wrap gap-2">
			<div class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm">
				{eventCount} events
			</div>
			<div class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm">
				{toolCount} tools
			</div>
			<div class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium shadow-sm {hasSpec ? 'text-emerald-700' : 'text-cyan-700'}">
				{hasSpec ? "SPEC ready" : statusLabel}
			</div>
		</div>
	</div>

	<div class="mt-4 grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
		<div class="space-y-4">
			<div class="rounded-[2rem] border border-white/60 bg-white/65 p-4 shadow-[0_12px_28px_rgba(15,23,42,0.06)]">
				<div class="flex items-center justify-between gap-3">
					<div>
						<p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
							Planner Status
						</p>
						<p class="mt-2 text-lg font-semibold text-slate-900">
							{primaryAgent?.name ?? "Root Architect"}
						</p>
					</div>
					<div class="flex items-center gap-2 rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-[11px] font-medium text-slate-600">
						{#if primaryAgent?.status === "complete" || hasSpec}
							<CheckCircle2 class="h-3.5 w-3.5 text-emerald-600" />
							Ready
						{:else if primaryAgent?.status === "error"}
							<XCircle class="h-3.5 w-3.5 text-rose-600" />
							Error
						{:else if isStreaming}
							<Loader2 class="h-3.5 w-3.5 animate-spin text-cyan-600" />
							Streaming
						{:else}
							<Clock3 class="h-3.5 w-3.5 text-slate-500" />
							Idle
						{/if}
					</div>
				</div>
				<p class="mt-3 text-sm leading-6 text-slate-600">
					{primaryAgent?.currentAction ||
						"Waiting for the planner to start building context."}
				</p>

				<div class="mt-4 grid grid-cols-3 gap-3">
					<div class="rounded-2xl border border-white/70 bg-white/85 p-3">
						<p class="text-[11px] text-slate-500">Progress</p>
						<p class="mt-1 text-lg font-semibold text-slate-900">
							{primaryAgent?.progress.percent ?? 0}%
						</p>
					</div>
					<div class="rounded-2xl border border-white/70 bg-white/85 p-3">
						<p class="text-[11px] text-slate-500">Events</p>
						<p class="mt-1 text-lg font-semibold text-slate-900">
							{primaryAgent?.events.length ?? 0}
						</p>
					</div>
					<div class="rounded-2xl border border-white/70 bg-white/85 p-3">
						<p class="text-[11px] text-slate-500">Tools</p>
						<p class="mt-1 text-lg font-semibold text-slate-900">
							{primaryAgent?.toolCalls.length ?? 0}
						</p>
					</div>
				</div>
			</div>

			<div class="rounded-[2rem] border border-white/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.82),rgba(245,250,255,0.72))] p-4 shadow-[0_12px_28px_rgba(15,23,42,0.06)]">
				<p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
					Reasoning Snapshot
				</p>
				<div class="mt-3 rounded-[1.5rem] border border-amber-200/55 bg-amber-50/55 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]">
					<div class="mb-2 flex items-center gap-2 text-amber-700">
						<Brain class="h-4 w-4" />
						<span class="text-[11px] font-semibold uppercase tracking-[0.14em]">
							Live thought stream
						</span>
					</div>
					<p class="max-h-[18rem] overflow-hidden whitespace-pre-wrap font-mono text-[12px] leading-6 text-slate-700">
						{reasoningPreview}
					</p>
				</div>
			</div>
		</div>

		<div class="rounded-[2.25rem] border border-white/65 bg-white/75 shadow-[0_16px_40px_rgba(15,23,42,0.08)]">
			<div class="flex items-center justify-between gap-3 border-b border-white/60 px-4 py-3">
				<div>
					<div class="flex items-center gap-2">
						<FileCode2 class="h-4 w-4 text-cyan-700" />
						<span class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
							Planning Timeline
						</span>
					</div>
					<p class="mt-1 text-sm text-slate-600">
						Chronological trace of context building, tool usage, and plan assembly.
					</p>
				</div>
				<div class="rounded-full border border-white/70 bg-white/85 px-3 py-1 text-[11px] font-medium text-slate-600">
					{timelineEvents.length} recent
				</div>
			</div>

			<div class="max-h-[760px] overflow-y-auto px-4 py-4">
				<div class="space-y-3">
					{#if timelineEvents.length > 0}
						{#each timelineEvents as event (event.eventKey)}
							{@const meta = getEventMeta(event.type)}
							{@const EventIcon = meta.icon}
							<div class="rounded-[1.75rem] border p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_38px_rgba(15,23,42,0.08)] {meta.className}">
								<div class="flex items-start justify-between gap-4">
									<div class="flex min-w-0 gap-3">
										<div class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-white/70 bg-white/80">
											<EventIcon class="h-4 w-4" />
										</div>
										<div class="min-w-0">
											<div class="flex flex-wrap items-center gap-2">
												<span class="rounded-full border border-white/70 bg-white/80 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em]">
													{meta.label}
												</span>
												<span class="text-[11px] font-medium text-slate-500">
													{event.agentName}
												</span>
											</div>
											<p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">
												{event.content || "No summary content provided."}
											</p>
											{#if event.data && Object.keys(event.data).length > 0}
												<div class="mt-3 flex flex-wrap gap-2">
													{#if event.data.tool}
														<span class="rounded-full border border-white/70 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-slate-600">
															Tool: {String(event.data.tool)}
														</span>
													{/if}
													{#if event.data.percent !== undefined}
														<span class="rounded-full border border-white/70 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-slate-600">
															{String(event.data.percent)}%
														</span>
													{/if}
													{#if event.data.estimated_tokens !== undefined}
														<span class="rounded-full border border-white/70 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-slate-600">
															{String(event.data.estimated_tokens)} tokens
														</span>
													{/if}
													{#if event.data.rag_chunks !== undefined}
														<span class="rounded-full border border-white/70 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-slate-600">
															{String(event.data.rag_chunks)} context chunks
														</span>
													{/if}
												</div>
											{/if}
										</div>
									</div>
									<span class="shrink-0 text-[11px] font-medium text-slate-500">
										{formatTimestamp(event.timestamp)}
									</span>
								</div>
							</div>
						{/each}
					{:else}
						<div class="rounded-[1.75rem] border border-dashed border-white/70 bg-white/55 px-4 py-10 text-center">
							<p class="text-sm font-medium text-slate-700">
								No planning events yet
							</p>
							<p class="mt-1 text-[12px] text-slate-500">
								Once Root Architect starts, context, reasoning, and tool events will stream here.
							</p>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<div class="xl:col-span-2 rounded-[2rem] border border-white/60 bg-white/60 p-4 shadow-[0_12px_28px_rgba(15,23,42,0.06)]">
			<div class="flex items-center gap-2">
				<Wrench class="h-4 w-4 text-sky-600" />
				<p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
					Recent Tool Activity
				</p>
			</div>
			<div class="mt-3 grid gap-3 xl:grid-cols-2">
				{#if recentToolCalls.length > 0}
					{#each recentToolCalls as event (event.id)}
						<div class="rounded-2xl border border-sky-100/80 bg-sky-50/55 px-3 py-3">
							<div class="flex items-start justify-between gap-3">
								<div>
									<p class="text-sm font-medium text-slate-900">
										{String(event.data?.tool ?? event.content ?? "Tool invocation")}
									</p>
									<p class="mt-1 text-[12px] leading-5 text-slate-600">
										{event.content}
									</p>
								</div>
								<span class="shrink-0 text-[11px] font-medium text-slate-500">
									{formatTimestamp(event.timestamp)}
								</span>
							</div>
						</div>
					{/each}
				{:else}
					<div class="xl:col-span-2 rounded-2xl border border-dashed border-white/70 bg-white/55 px-3 py-5 text-center text-[12px] text-slate-500">
						Tool invocations will appear here once planning begins.
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
