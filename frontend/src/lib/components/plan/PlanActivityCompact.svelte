<script lang="ts">
	import { tick } from "svelte";
	import type { AgentStream, AgentStreamEvent } from "$lib/agent-registry.svelte";
	import * as Card from "$lib/components/ui/card";
	import { ScrollArea } from "$lib/components/ui/scroll-area";
	import Brain from "@lucide/svelte/icons/brain";
	import CheckCircle2 from "@lucide/svelte/icons/check-circle-2";
	import Clock3 from "@lucide/svelte/icons/clock-3";
	import Loader2 from "@lucide/svelte/icons/loader-2";
	import TerminalSquare from "@lucide/svelte/icons/terminal-square";
	import Wrench from "@lucide/svelte/icons/wrench";
	import XCircle from "@lucide/svelte/icons/x-circle";

	let {
		agents,
		isStreaming = false,
		hasSpec = false,
		statusLabel = "Waiting",
	}: {
		agents: AgentStream[];
		isStreaming?: boolean;
		hasSpec?: boolean;
		statusLabel?: string;
	} = $props();

	let traceViewport: HTMLElement | null = $state(null);
	let shouldFollowTrace = $state(true);
	let traceSignature = $state("");

	const visibleAgents = $derived(
		agents.filter((agent) => agent.id === "agent-rootdep" || agent.events.length > 0),
	);
	const primaryAgent = $derived(
		visibleAgents.find((agent) => agent.id === "agent-rootdep") ?? visibleAgents[0] ?? null,
	);
	const eventCount = $derived(visibleAgents.reduce((sum, agent) => sum + agent.events.length, 0));
	const toolCount = $derived(visibleAgents.reduce((sum, agent) => sum + agent.toolCalls.length, 0));
	const timelineEvents = $derived.by(() => {
		const items: Array<AgentStreamEvent & { agentName: string; eventKey: string }> = [];
		for (const agent of visibleAgents) {
			for (const event of agent.events) {
				if (event.type === "thinking" || event.type === "reasoning") continue;
				items.push({ ...event, agentName: agent.name, eventKey: `${agent.id}-${event.id}` });
			}
		}
		return items.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()).slice(-20);
	});
	const recentTools = $derived.by(() => [...(primaryAgent?.toolCalls ?? [])].slice(-8));
	const reasoning = $derived(formatThinkingContent(primaryAgent?.thinking || ""));

	function formatThinkingContent(content: string): string {
		return content
			.replace(/<\/?(think|thinking|thought|thing)\b[^>]*>/gi, "")
			.trim();
	}

	function handleTraceScroll() {
		if (!traceViewport) return;
		shouldFollowTrace = traceViewport.scrollHeight - traceViewport.scrollTop - traceViewport.clientHeight <= 120;
	}

	function scrollTraceToLatest(behavior: ScrollBehavior = "smooth") {
		if (!traceViewport) return;
		traceViewport.scrollTo({ top: traceViewport.scrollHeight, behavior });
	}

	$effect(() => {
		const signature = `${timelineEvents.map((event) => event.eventKey).join("|")}:${timelineEvents.length}`;
		if (!traceViewport || signature === traceSignature) return;
		const firstRun = !traceSignature;
		traceSignature = signature;
		if (!shouldFollowTrace && !firstRun) return;
		tick().then(() => scrollTraceToLatest(firstRun ? "auto" : "smooth"));
	});

	$effect(() => {
		if (!traceViewport) return;
		const viewport = traceViewport;
		viewport.addEventListener("scroll", handleTraceScroll, { passive: true });
		return () => viewport.removeEventListener("scroll", handleTraceScroll);
	});

	function formatTimestamp(timestamp: number | string) {
		return new Date(timestamp).toLocaleTimeString([], {
			hour: "2-digit",
			minute: "2-digit",
			second: "2-digit",
		});
	}

	function eventLabel(type: string) {
		if (type === "tool_start" || type === "tool_call" || type === "tool_result") return "Tool";
		if (type === "context_built" || type === "context_compacted") return "Context";
		if (type === "progress" || type === "state") return "Progress";
		if (type === "complete" || type === "PlanReady") return "Done";
		if (type === "error" || type === "RunError") return "Error";
		return "Event";
	}

	function eventTone(type: string) {
		if (type === "error" || type === "RunError") return "bad";
		if (type === "complete" || type === "PlanReady") return "good";
		if (type === "tool_start" || type === "tool_call" || type === "tool_result") return "tool";
		return "neutral";
	}

	function toolName(event: AgentStreamEvent) {
		return String(event.data?.tool || event.content || "Tool invocation");
	}
</script>

<Card.Root class="plan-activity" size="sm">
	<Card.Header class="plan-activity-head">
		<div>
			<span class="eyebrow compact">Live trace</span>
			<Card.Title>Planner activity</Card.Title>
			<Card.Description>{primaryAgent?.currentAction || statusLabel}</Card.Description>
		</div>
		<div class="plan-status-pill" class:done={hasSpec} class:streaming={isStreaming && !hasSpec}>
			{#if hasSpec}
				<CheckCircle2 size={14} />
				SPEC ready
			{:else if isStreaming}
				<Loader2 size={14} class="animate-spin" />
				Streaming
			{:else if primaryAgent?.status === "error"}
				<XCircle size={14} />
				Error
			{:else}
				<Clock3 size={14} />
				{statusLabel}
			{/if}
		</div>
	</Card.Header>

	<Card.Content class="plan-activity-grid">
		<section class="plan-status">
			<div class="plan-metrics">
				<div><span>Progress</span><b>{primaryAgent?.progress.percent ?? 0}%</b></div>
				<div><span>Events</span><b>{eventCount}</b></div>
				<div><span>Tools</span><b>{toolCount}</b></div>
			</div>

			<div class="reasoning-block">
				<div class="section-label"><Brain size={14} /> Reasoning</div>
				{#if reasoning}
					<p>{reasoning}</p>
				{:else}
					<p class="muted">No reasoning summary yet.</p>
				{/if}
			</div>
		</section>

		<section class="plan-timeline">
			<div class="section-label"><TerminalSquare size={14} /> Timeline</div>
			<ScrollArea class="plan-trace-scroll" bind:viewportRef={traceViewport}>
				{#if timelineEvents.length > 0}
					<div class="trace-list">
						{#each timelineEvents as event (event.eventKey)}
							<article class="trace-item {eventTone(event.type)}">
								<div class="trace-time">{formatTimestamp(event.timestamp)}</div>
								<div class="trace-body">
									<div class="trace-title">
										<span>{eventLabel(event.type)}</span>
										<em>{event.agentName}</em>
									</div>
									{#if formatThinkingContent(event.content || "")}
										<p>{formatThinkingContent(event.content || "")}</p>
									{/if}
									{#if event.data?.tool}
										<small>{String(event.data.tool)}</small>
									{/if}
								</div>
							</article>
						{/each}
					</div>
				{:else}
					<p class="empty-line">No timeline events yet.</p>
				{/if}
			</ScrollArea>
		</section>

		<section class="plan-tools">
			<div class="section-label"><Wrench size={14} /> Tools</div>
			{#if recentTools.length > 0}
				<div class="tool-list">
					{#each recentTools as event (event.id)}
						<div class="tool-row">
							<span>{formatTimestamp(event.timestamp)}</span>
							<b title={toolName(event)}>{toolName(event)}</b>
						</div>
					{/each}
				</div>
			{:else}
				<p class="empty-line">No tool calls yet.</p>
			{/if}
		</section>
	</Card.Content>
</Card.Root>

<style>
	:global(.plan-activity) {
		background:
			linear-gradient(145deg, rgba(255,255,255,0.78), rgba(255,255,255,0.54)),
			radial-gradient(95% 150% at 100% 0%, oklch(80% 0.13 220 / 0.18), transparent 58%),
			var(--paper-0);
		border: 1px solid rgba(255,255,255,0.64);
		border-radius: 22px;
		box-shadow: var(--shadow-2);
		backdrop-filter: blur(24px) saturate(140%);
		-webkit-backdrop-filter: blur(24px) saturate(140%);
		padding: 0;
		overflow: hidden;
	}

	:global(.plan-activity-head) {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		padding: 18px 18px 14px;
		border-bottom: 1px solid rgba(255,255,255,0.66);
	}

	:global(.plan-activity-head [data-slot="card-title"]) {
		margin-top: 6px;
		font-family: var(--font-display);
		font-size: 30px;
		font-weight: 400;
		line-height: 1;
		letter-spacing: -0.015em;
		color: var(--ink-0);
	}

	:global(.plan-activity-head [data-slot="card-description"]) {
		margin-top: 5px;
		color: var(--ink-4);
		font-size: 13px;
		line-height: 1.45;
	}

	.plan-status-pill {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: rgba(255,255,255,0.62);
		color: var(--ink-4);
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.06em;
		padding: 6px 10px;
		white-space: nowrap;
	}

	.plan-status-pill.streaming { color: var(--violet-d); border-color: oklch(85% 0.06 295); }
	.plan-status-pill.done { color: oklch(45% 0.14 150); border-color: oklch(84% 0.07 150); }

	:global(.plan-activity-grid) {
		display: grid;
		grid-template-columns: minmax(220px, 0.8fr) minmax(0, 1.2fr);
		gap: 1px;
		padding: 0;
		background: rgba(255,255,255,0.54);
	}

	.plan-status,
	.plan-timeline,
	.plan-tools {
		background: rgba(255,255,255,0.54);
		padding: 16px;
		min-width: 0;
	}

	.plan-tools { grid-column: 1 / -1; border-top: 1px solid rgba(255,255,255,0.62); }

	.plan-metrics {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
		margin-bottom: 16px;
	}

	.plan-metrics div {
		border: 1px solid var(--line);
		border-radius: 8px;
		background: rgba(255,255,255,0.54);
		padding: 10px;
	}

	.plan-metrics span,
	.trace-time,
	.tool-row span {
		display: block;
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.06em;
		color: var(--ink-5);
	}

	.plan-metrics b {
		display: block;
		margin-top: 4px;
		font-family: var(--font-display);
		font-size: 24px;
		font-weight: 400;
		line-height: 1;
		color: var(--ink-0);
	}

	.section-label {
		display: flex;
		align-items: center;
		gap: 7px;
		margin-bottom: 10px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--ink-5);
	}

	.reasoning-block p {
		margin: 0;
		max-height: 180px;
		overflow: hidden;
		white-space: pre-wrap;
		font-family: var(--font-mono);
		font-size: 12px;
		line-height: 1.6;
		color: var(--ink-3);
	}

	.reasoning-block .muted,
	.empty-line {
		color: var(--ink-5);
		font-family: inherit;
		font-size: 13px;
	}

	:global(.plan-trace-scroll) { height: 300px; }
	.trace-list { display: flex; flex-direction: column; gap: 8px; padding-right: 10px; }

	.trace-item {
		display: grid;
		grid-template-columns: 68px minmax(0, 1fr);
		gap: 10px;
		border-left: 2px solid var(--line);
		padding: 8px 0 9px 10px;
	}

	.trace-item.tool { border-left-color: var(--cyan-d); }
	.trace-item.good { border-left-color: oklch(62% 0.14 150); }
	.trace-item.bad { border-left-color: var(--rose); }

	.trace-title {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.trace-title span {
		font-size: 12px;
		font-weight: 600;
		color: var(--ink-1);
	}

	.trace-title em {
		font-style: normal;
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--ink-5);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.trace-body p {
		margin: 4px 0 0;
		color: var(--ink-3);
		font-size: 13px;
		line-height: 1.45;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.trace-body small {
		display: inline-block;
		margin-top: 6px;
		border: 1px solid var(--line);
		border-radius: 6px;
		background: rgba(255,255,255,0.58);
		padding: 2px 6px;
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--ink-4);
	}

	.tool-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
	}

	.tool-row {
		display: grid;
		grid-template-columns: 62px minmax(0, 1fr);
		gap: 8px;
		align-items: center;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: rgba(255,255,255,0.58);
		padding: 8px 10px;
	}

	.tool-row b {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12.5px;
		font-weight: 500;
		color: var(--ink-2);
	}

	@media (max-width: 900px) {
		:global(.plan-activity-grid) { grid-template-columns: 1fr; }
		.plan-tools { grid-column: auto; }
		.tool-list { grid-template-columns: 1fr; }
	}
</style>
