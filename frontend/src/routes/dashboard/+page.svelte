<script lang="ts">
	import { onMount, onDestroy, tick } from "svelte";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Textarea } from "$lib/components/ui/textarea";
	import * as Card from "$lib/components/ui/card";
	import { ScrollArea } from "$lib/components/ui/scroll-area";
	import MarkdownContent from "$lib/components/chat/MarkdownContent.svelte";
	import {
		GlobalProgress,
		VersionHistory,
	} from "$lib/components/mesh";
	import { DownloadButtons } from "$lib/components/chat";
	import PlanSpecPreview from "$lib/components/plan/PlanSpecPreview.svelte";
	import PlanActivityPanel from "$lib/components/plan/PlanActivityPanel.svelte";
	import { agentRegistry } from "$lib/agent-registry.svelte";
	import { AGUIClient } from "$lib/aguiclient";
	import ProjectSidebar from "$lib/components/ProjectSidebar.svelte";
	import CodeView from "$lib/components/codeview/CodeView.svelte";
	import Send from '@lucide/svelte/icons/send';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import Hexagon from '@lucide/svelte/icons/hexagon';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import History from '@lucide/svelte/icons/history';
	import PanelLeftOpen from '@lucide/svelte/icons/panel-left-open';
	import Map from '@lucide/svelte/icons/map';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import MessageSquare from '@lucide/svelte/icons/message-square';
	import Play from '@lucide/svelte/icons/play';
	import Eye from '@lucide/svelte/icons/eye';
	import Code2 from '@lucide/svelte/icons/code-2';
	import Settings from '@lucide/svelte/icons/settings';
	import Square from '@lucide/svelte/icons/square';
	import Plus from '@lucide/svelte/icons/plus';
	import Search from '@lucide/svelte/icons/search';
	import Pause from '@lucide/svelte/icons/pause';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Zap from '@lucide/svelte/icons/zap';
	import X from '@lucide/svelte/icons/x';
	import { settings } from "$lib/settings.svelte";

	let inputValue = $state("");
	let aguiClient: AGUIClient | null = null;
	let activeProjectId = $state<string | null>(null);
	type QuestionType = 'text' | 'textarea' | 'single_select' | 'multi_select' | 'boolean';
	type QuestionItem = {
		id: string;
		label: string;
		type: QuestionType;
		options: string[];
		required: boolean;
		help?: string;
	};
	type PendingQuestion = {
		question_id: string;
		questions: QuestionItem[];
	};

	let pendingQuestion = $state<PendingQuestion | null>(null);
	let questionAnswers = $state<string[]>([]);
	let isSubmittingAnswers = $state(false);
	let isSidebarCollapsed = $state(false);
	let isMobile = $state(false);
	let showVersionHistory = $state(false);
	let isPlanMode = $state(false);
	let planResponse = $state<string | null>(null);
	let isExecutingPlan = $state(false);
	let isCodeViewCollapsed = $state(true);
	let workspaceFiles = $state<any[]>([]);
	let lastWrittenFile = $state<{ path: string; ts: number; content?: string; phase?: string } | undefined>(undefined);
	let _fileRefreshTimer: ReturnType<typeof setTimeout> | null = null;
	let _workspaceLoadSeq = 0;
	let specContent = $state<string | null>(null);
	let isEditingSpec = $state(false);
	let editedSpecContent = $state("");
	let agentDetailBody: HTMLDivElement | null = $state(null);
	let shouldFollowAgentDetail = $state(true);
	let lastAgentScrollSignature = "";

	let chatHistory = $state<
		{ role: "user" | "assistant"; content: string; metadata?: any; tools?: { type: string; content?: string; data?: any }[] }[]
	>([]);

	type ProjectStatusSnapshot = {
		project_id: string;
		status: string;
		error?: string | null;
		run_mode?: string | null;
		context_mode?: string | null;
		checkpoint_id?: string | null;
		spec?: Record<string, any>;
		spec_content?: string | null;
		source?: string;
	};

	const selectedAgent = $derived(agentRegistry.selectedAgent);
	const allAgents = $derived(agentRegistry.allAgents);
	const isRunning = $derived(agentRegistry.isRunning);
	const globalProgress = $derived(agentRegistry.globalProgress);
	const downloadReady = $derived(agentRegistry.downloadReady);
	const downloadData = $derived(agentRegistry.downloadData);
	const hasError = $derived(agentRegistry.hasError);
	const errorMessage = $derived(agentRegistry.errorMessage);
	const planMetrics = $derived(
		getPlanMetrics(editedSpecContent || specContent || ""),
	);
	const planAgents = $derived(
		allAgents.filter(
			(agent) =>
				agent.id === "agent-rootdep" ||
				agent.id === "agent-system" ||
				agent.events.length > 0,
		),
	);
	const hasPlanTelemetry = $derived(
		planAgents.some(
			(agent) =>
				agent.events.length > 0 ||
				agent.toolCalls.length > 0 ||
				Boolean(agent.thinking.trim()),
		),
	);
	const planActivityStatusLabel = $derived.by(() => {
		if (specContent) return "SPEC ready";
		if (isExecutingPlan || isRunning) return "Generating plan";
		if (hasPlanTelemetry) return "Trace captured";
		return "Waiting";
	});

	function splitQuestionOptions(raw: string): string[] {
		return raw
			.replace(/\s+\/\s+/g, ',')
			.replace(/\s+or\s+/gi, ',')
			.split(',')
			.map((part) => part.trim().replace(/^[-•]\s*/, ''))
			.filter(Boolean);
	}

	function normalizeQuestionType(value: unknown, hasOptions: boolean): QuestionType {
		const raw = String(value || '').toLowerCase();
		const mapped: Record<string, QuestionType> = {
			select: 'single_select',
			radio: 'single_select',
			choice: 'single_select',
			choices: 'single_select',
			checkbox: 'multi_select',
			checkboxes: 'multi_select',
			multi: 'multi_select',
			multiselect: 'multi_select',
			long_text: 'textarea',
			boolean: 'boolean',
			yes_no: 'boolean',
		};
		return mapped[raw] || (['text', 'textarea', 'single_select', 'multi_select', 'boolean'].includes(raw) ? raw as QuestionType : hasOptions ? 'single_select' : 'text');
	}

	function normalizeQuestion(raw: unknown, index: number): QuestionItem {
		if (raw && typeof raw === 'object') {
			const data = raw as Record<string, any>;
			const label = String(data.label || data.question || data.text || `Question ${index + 1}`);
			const options = Array.isArray(data.options || data.choices)
				? (data.options || data.choices).map((option: any) => String(typeof option === 'object' ? option.label || option.value : option).trim()).filter(Boolean)
				: [];
			const type = normalizeQuestionType(data.type || data.kind || data.input_type, options.length > 0);
			return {
				id: String(data.id || `q_${index}`),
				label,
				type,
				options: type === 'boolean' && options.length === 0 ? ['Yes', 'No'] : options,
				required: data.required !== false,
				help: data.help || data.description,
			};
		}

		const label = String(raw || `Question ${index + 1}`);
		const lower = label.toLowerCase();
		let options: string[] = [];
		let type: QuestionType = 'text';
		const marker = ['options:', 'choices:', 'choose one:', 'select one:'].find((candidate) => lower.includes(candidate));
		if (marker) {
			options = splitQuestionOptions(label.slice(lower.indexOf(marker) + marker.length));
			type = 'single_select';
		}
		if (!options.length) {
			const exampleMatch = label.match(/\((?:e\.g\.|for example)\s+([^)]+)\)/i);
			if (exampleMatch) {
				options = splitQuestionOptions(exampleMatch[1]);
				if (options.length > 1 && /\b(which|what|choose|select|prefer|should i use)\b/i.test(label)) type = 'single_select';
			}
		}
		if (/select all|choose all|multiple/i.test(label)) type = options.length ? 'multi_select' : 'textarea';
		if (type === 'text' && /^(do|does|should|would|is|are|can)\b/i.test(label)) {
			type = 'boolean';
			options = ['Yes', 'No'];
		}
		if (type === 'text' && /\b(describe|details|requirements|constraints|notes)\b/i.test(label)) type = 'textarea';
		return { id: `q_${index}`, label, type, options, required: true };
	}

	function normalizePendingQuestion(data: any): PendingQuestion | null {
		if (!data?.question_id) return null;
		const rawItems = Array.isArray(data.question_items) ? data.question_items : data.questions;
		if (!Array.isArray(rawItems)) return null;
		return {
			question_id: String(data.question_id),
			questions: rawItems.map(normalizeQuestion),
		};
	}

	function setQuestionAnswer(index: number, value: string) {
		questionAnswers = questionAnswers.map((answer, i) => i === index ? value : answer);
	}

	function selectedMultiValues(index: number): string[] {
		return questionAnswers[index]?.split(',').map((part) => part.trim()).filter(Boolean) || [];
	}

	function toggleMultiAnswer(index: number, option: string) {
		const selected = selectedMultiValues(index);
		const next = selected.includes(option)
			? selected.filter((item) => item !== option)
			: [...selected, option];
		setQuestionAnswer(index, next.join(', '));
	}

	function canSubmitPendingQuestion(): boolean {
		if (!pendingQuestion) return false;
		return pendingQuestion.questions.every((question, index) => {
			if (!question.required) return true;
			return Boolean(questionAnswers[index]?.trim());
		});
	}

	function summarizeAnswers(question: PendingQuestion, answers: string[]): string {
		return question.questions
			.map((item, index) => `${item.label}: ${answers[index] || 'No answer'}`)
			.join('\n');
	}

	function isNearAgentDetailLiveEdge(el: HTMLDivElement, tab = agentDetailTab): boolean {
		if (tab === 'timeline') return el.scrollTop <= 80;
		return el.scrollHeight - el.scrollTop - el.clientHeight <= 120;
	}

	function handleAgentDetailScroll() {
		if (!agentDetailBody) return;
		shouldFollowAgentDetail = isNearAgentDetailLiveEdge(agentDetailBody);
	}

	function scrollAgentDetailToLatest(behavior: ScrollBehavior = 'smooth') {
		if (!agentDetailBody) return;
		const top = agentDetailTab === 'timeline' ? 0 : agentDetailBody.scrollHeight;
		agentDetailBody.scrollTo({ top, behavior });
	}

	$effect(() => {
		const agentId = selectedAgent?.id || '';
		const tab = agentDetailTab;
		const eventCount = selectedAgent?.events.filter((e) => e.type !== 'thinking' && e.type !== 'reasoning').length || 0;
		const thinkingCount = selectedAgent?.events.filter((e) => (e.type === 'thinking' || e.type === 'reasoning') && stripThinkTags(e.content || '').trim()).length || 0;
		const toolCount = selectedAgent?.toolCalls.length || 0;
		const taskCount = selectedAgent?.tasks.length || 0;
		const completedTaskCount = selectedAgent?.tasks.filter((task) => task.completed).length || 0;
		const signature = `${agentId}:${tab}:${eventCount}:${thinkingCount}:${toolCount}:${taskCount}:${completedTaskCount}`;
		const previous = lastAgentScrollSignature;
		const scopeChanged = !previous.startsWith(`${agentId}:${tab}:`);

		if (!agentDetailBody || signature === previous) return;
		lastAgentScrollSignature = signature;

		if (scopeChanged) shouldFollowAgentDetail = true;
		if (!shouldFollowAgentDetail && !scopeChanged) return;

		tick().then(() => {
			scrollAgentDetailToLatest(scopeChanged ? 'auto' : 'smooth');
		});
	});

	async function handleSubmit() {
		const message = inputValue.trim();
		if (!message || isRunning) return;

		chatHistory = [...chatHistory, { role: "user", content: message }];
		inputValue = "";

		if (isPlanMode && !isExecutingPlan) {
			isExecutingPlan = true;
			specContent = null;
			planResponse = null;
			chatHistory = [
				...chatHistory,
				{
					role: "assistant",
					content: `Planning mode: Analyzing your request to create a detailed implementation plan...\n\nThis may take a moment as I explore the codebase and create a step-by-step plan.`,
				},
			];
			try {
				const res = await fetch("/api/plan", {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						message,
						project_id: activeProjectId,
						mode: activeProjectId ? "modify" : "generate",
					}),
				});
				if (res.ok) {
					const data = await res.json();
					const projectId = data.project_id;
					activeProjectId = projectId;
					localStorage.setItem("chorus.activeProjectId", projectId);
					agentRegistry.reset();
					agentRegistry.isRunning = true;
					planResponse = "Plan generation in progress...";
					connectStream(projectId, "auto", "generate", "plan");
				} else {
					chatHistory = [
						...chatHistory,
						{
							role: "assistant",
							content:
								"Plan mode is not available. Please use Build mode to generate the project.",
						},
					];
					isExecutingPlan = false;
				}
			} catch (e) {
				chatHistory = [
					...chatHistory,
					{
						role: "assistant",
						content:
							"Failed to generate plan. Please try again or switch to Build mode.",
					},
				];
				isExecutingPlan = false;
			}
			return;
		}

		if (planResponse && !isExecutingPlan) {
			planResponse = null;
		}

		const res = await fetch("/api/chat", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				message,
				project_id: activeProjectId,
				mode: activeProjectId ? "modify" : "generate",
				context_mode: $settings.defaultContextMode,
			}),
		});

		if (!res.ok) {
			const errData = await res.json().catch(() => ({}));
			if (res.status === 422 && errData.error === "vague_request") {
				chatHistory = [
					...chatHistory,
					{
						role: "assistant",
						content: `I need more detail to help you. ${errData.clarification || "Please describe your project more specifically."}`,
					},
				];
				return;
			}
			throw new Error(`HTTP ${res.status}`);
		}

		const data = await res.json();
		const projectId = data.project_id;
		const contextMode = data.context_mode || "auto";
		const runMode = data.mode || (activeProjectId ? "modify" : "generate");
		activeProjectId = projectId;
		localStorage.setItem("chorus.activeProjectId", projectId);
		agentRegistry.reset();
		agentRegistry.isRunning = true;
		planResponse = null;
		connectStream(projectId, contextMode, runMode);
	}

	async function handleExecutePlan() {
		if (!specContent || isRunning) return;
		const message = chatHistory.find((m) => m.role === "user")?.content;
		if (!message) return;

		chatHistory = [
			...chatHistory,
			{
				role: "assistant",
				content: `Approving the plan and starting implementation...`,
			},
		];

		isExecutingPlan = true;
		planResponse = "Plan approved. Implementation is starting...";

		const res = await fetch("/api/approve", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				project_id: activeProjectId,
				message,
				spec_content: editedSpecContent,
			}),
		});

		if (res.ok) {
			const data = await res.json();
			const projectId = data.project_id;
			isPlanMode = false;
			activeProjectId = projectId;
			localStorage.setItem("chorus.activeProjectId", projectId);
			agentRegistry.reset();
			agentRegistry.isRunning = true;
			specContent = null;
			editedSpecContent = "";
			isEditingSpec = false;
			planResponse = null;
			connectStream(projectId, "auto", data.mode || "approved", "build");
		} else {
			chatHistory = [
				...chatHistory,
				{
					role: "assistant",
					content: "Failed to approve the plan. Please try again.",
				},
			];
		}
		isExecutingPlan = false;
	}

	function handleEditSpec() {
		editedSpecContent = specContent || "";
		isEditingSpec = true;
	}

	function handleCancelEditSpec() {
		isEditingSpec = false;
		editedSpecContent = specContent || "";
	}

	function handleSaveSpec() {
		specContent = editedSpecContent;
		isEditingSpec = false;
	}

	async function handlePauseAgent(agentId: string) {
		if (!activeProjectId) return;
		const name = agentId.replace('agent-', '');
		try {
			const res = await fetch(`/api/projects/${activeProjectId}/agents/${name}/pause`, { method: 'POST' });
			if (!res.ok) console.error('Failed to pause agent:', await res.text());
		} catch (e) {
			console.error('Pause error:', e);
		}
	}

	async function handleResumeAgent(agentId: string, message: string) {
		if (!activeProjectId) return;
		const name = agentId.replace('agent-', '');
		try {
			const res = await fetch(`/api/projects/${activeProjectId}/agents/${name}/resume`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ message }),
			});
			if (!res.ok) console.error('Failed to resume agent:', await res.text());
		} catch (e) {
			console.error('Resume error:', e);
		}
	}

	async function handleDirectAgent(agentId: string, message: string) {
		if (!activeProjectId) return;
		const name = agentId.replace('agent-', '');
		try {
			const res = await fetch(`/api/projects/${activeProjectId}/directive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ agent: name, message }),
			});
			if (!res.ok) console.error('Failed to send directive:', await res.text());
		} catch (e) {
			console.error('Directive error:', e);
		}
	}

	async function handleStopSwarm() {
		if (!activeProjectId) return;
		try {
			const res = await fetch(`/api/projects/${activeProjectId}/swarm/stop`, { method: 'POST' });
			if (!res.ok) console.error('Failed to stop swarm:', await res.text());
		} catch (e) {
			console.error('Stop swarm error:', e);
		}
	}

	async function submitAnswers() {
		if (!pendingQuestion || !activeProjectId || isSubmittingAnswers) return;
		const answeredQuestion = pendingQuestion;
		const answers = [...questionAnswers];
		isSubmittingAnswers = true;
		try {
			const res = await fetch(`/api/projects/${activeProjectId}/answer`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					question_id: answeredQuestion.question_id,
					answers,
					questions: answeredQuestion.questions,
					ui_mode: isPlanMode ? 'plan' : 'build',
				}),
			});
			if (!res.ok) throw new Error(await res.text());
			chatHistory = [
				...chatHistory,
				{
					role: "user",
					content: summarizeAnswers(answeredQuestion, answers),
					metadata: { type: "question_answers", question_id: answeredQuestion.question_id },
				},
			];
			pendingQuestion = null;
			questionAnswers = [];
		} catch (e) {
			console.error('Failed to submit answers:', e);
		} finally {
			isSubmittingAnswers = false;
		}
	}

	function getPlanMetrics(spec: string) {
		const normalized = spec.trim();
		const lines = spec ? spec.split(/\r?\n/).length : 0;
		const words = normalized ? normalized.split(/\s+/).length : 0;
		const headings = (spec.match(/^#{1,6}\s+/gm) || []).length;
		const listItems = (spec.match(/^\s*[-*+]\s+/gm) || []).length;
		const mermaidBlocks = (spec.match(/```mermaid/gi) || []).length;
		const codeBlocks = Math.floor((spec.match(/```/g) || []).length / 2);

		return {
			lines,
			words,
			headings,
			listItems,
			mermaidBlocks,
			codeBlocks,
		};
	}

	function setPlanMode(next: boolean) {
		if (isPlanMode === next) return;
		isPlanMode = next;
		if (isPlanMode) {
			chatHistory = [
				...chatHistory,
				{
					role: "assistant",
					content:
						"**Plan Mode** activated. When you describe what you want to build, I will create a detailed implementation plan for your review before writing any code.\n\nClick **Execute** to run the plan, or continue chatting to refine it.",
				},
			];
		}
	}

	function connectStream(
		projectId: string,
		contextMode: string,
		mode: string,
		uiMode: string = "build",
	) {
		if (aguiClient) {
			aguiClient.disconnect();
		}

		aguiClient = new AGUIClient({
			onOpen: (streamProjectId) => {
				if (activeProjectId !== streamProjectId) return;
				warmupAndLoadFiles(streamProjectId);
			},
			onRawEvent: (event) => {
				agentRegistry.dispatchEvent(event);
				if (
					event.type === "RunStarted" ||
					event.type === "RunFinished" ||
					event.type === "download_ready"
				) {
					const eventProjectId = event.data?.project_id as
						| string
						| undefined;
					if (eventProjectId) {
						activeProjectId = eventProjectId;
						localStorage.setItem(
							"chorus.activeProjectId",
							eventProjectId,
						);
					}
				}
				// Attach tool calls to the most recent assistant message so they render inline
				if (
					event.type === "tool_call" ||
					event.type === "tool_result" ||
					event.type === "tool_start"
				) {
					const lastIdx = chatHistory.length - 1;
					let targetIdx = -1;
					for (let i = lastIdx; i >= 0; i--) {
						if (chatHistory[i].role === "assistant") {
							targetIdx = i;
							break;
						}
					}
					if (targetIdx >= 0) {
						chatHistory = chatHistory.map((m, i) =>
							i === targetIdx
								? {
										...m,
										tools: [
											...(m.tools || []),
											{
												type: (event.data?.tool as string) || event.type,
												content: event.content || "",
												data: event.data,
											},
										],
									}
								: m,
						);
					}
				}
			},
			onText: (event) => {
				if (event.content) {
					chatHistory = [
						...chatHistory,
						{
							role: "assistant",
							content: `[${event.agent_name || "Agent"}]: ${event.content}`,
						},
					];
				}
			},
			onError: (event) => {
				console.error("SSE error event:", event);
				if (event.content === "Connection error") {
					return;
				}
				isExecutingPlan = false;
			},
			onPlanReady: (event) => {
				const incomingSpec = (event.data?.spec_content as string) || "";
				specContent = incomingSpec;
				editedSpecContent = incomingSpec;
				planResponse = "Plan ready for review.";
				isExecutingPlan = false;
				agentRegistry.isRunning = false;
				if (activeProjectId) {
					loadWorkspaceFiles(activeProjectId);
				}
			},
			onFileCreated: (event) => {
				const fp = event.data?.file_path as string | undefined;
				if (fp && activeProjectId === projectId) {
					lastWrittenFile = {
						path: fp,
						ts: Date.now(),
						content: typeof event.data?.content === "string" ? event.data.content : undefined,
						phase: typeof event.data?.phase === "string" ? event.data.phase : undefined,
					};
				}
				scheduleFileTreeRefresh(projectId);
			},
			onDirectoryCreated: () => {
				scheduleFileTreeRefresh(projectId);
			},
			onQuestion: (event) => {
				const normalized = normalizePendingQuestion(event.data);
				if (normalized) {
					pendingQuestion = normalized;
					questionAnswers = new Array(normalized.questions.length).fill('');
				}
			},
		});

		// Auto-open the code view when a build starts so users see files appear live
		if (mode === "generate" || mode === "approved" || mode === "modify" || uiMode === "plan") {
			isCodeViewCollapsed = false;
		}
		if (!isCodeViewCollapsed) {
			warmupAndLoadFiles(projectId);
		}

		aguiClient.connect(projectId, contextMode, mode, uiMode);
	}

	async function fetchProjectStatus(
		projectId: string,
	): Promise<ProjectStatusSnapshot | null> {
		try {
			const res = await fetch(`/api/status/${projectId}`);
			if (!res.ok) return null;
			return (await res.json()) as ProjectStatusSnapshot;
		} catch (e) {
			console.error("Failed to load project status:", e);
			return null;
		}
	}

	async function readSpecFromWorkspace(projectId: string) {
		try {
			const res = await fetch(
				`/api/workspace/${projectId}/read?path=${encodeURIComponent("SPEC.md")}`,
			);
			if (!res.ok) return null;
			const data = await res.json();
			return (data.content as string) || null;
		} catch (e) {
			console.error("Failed to read SPEC.md:", e);
			return null;
		}
	}

	function resetProjectViewState() {
		agentRegistry.reset();
		specContent = null;
		editedSpecContent = "";
		isEditingSpec = false;
		planResponse = null;
		showVersionHistory = false;
	}

	async function restoreProjectSession(projectId: string) {
		resetProjectViewState();

		const status = await fetchProjectStatus(projectId);
		await Promise.all([loadChatHistory(projectId), warmupAndLoadFiles(projectId)]);

		if (!status) {
			isPlanMode = false;
			return;
		}

		const normalizedStatus = status.status || "unknown";
		const runMode = status.run_mode || "generate";
		const contextMode = status.context_mode || "auto";

		if (normalizedStatus === "planning") {
			isPlanMode = true;
			isExecutingPlan = true;
			planResponse = "Plan generation in progress...";
			agentRegistry.isRunning = true;
			connectStream(projectId, contextMode, runMode, "plan");
			return;
		}

		if (normalizedStatus === "plan_ready") {
			isPlanMode = true;
			isExecutingPlan = false;
			const savedSpec =
				status.spec_content ||
				(typeof status.spec?.spec_content === "string"
					? status.spec.spec_content
					: null);
			const restoredSpec =
				savedSpec || (await readSpecFromWorkspace(projectId));
			specContent = restoredSpec || "";
			editedSpecContent = specContent;
			planResponse = specContent ? "Plan ready for review." : null;
			return;
		}

		isPlanMode = false;
		isExecutingPlan = false;

		if (normalizedStatus === "running") {
			agentRegistry.isRunning = true;
			connectStream(projectId, contextMode, runMode, "build");
			return;
		}

		if (
			normalizedStatus === "pending" &&
			runMode !== "plan" &&
			status.spec?.mode !== "new"
		) {
			agentRegistry.isRunning = true;
			connectStream(projectId, contextMode, runMode, "build");
			return;
		}

		agentRegistry.isRunning = false;
	}

	async function startNewProject() {
		if (aguiClient) {
			aguiClient.disconnect();
		}

		try {
			const res = await fetch("/api/projects", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					name: "New Project",
					message:
						"Describe the new Spring Boot + Svelte project you want to build.",
				}),
			});

			if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			}

			const data = await res.json();
			activeProjectId = data.project_id;
			localStorage.setItem("chorus.activeProjectId", data.project_id);
		} catch (e) {
			console.error("Failed to create new project:", e);
			activeProjectId = null;
			localStorage.removeItem("chorus.activeProjectId");
		}

		resetProjectViewState();
		showVersionHistory = false;
		isCodeViewCollapsed = true;
		isPlanMode = false;
		isExecutingPlan = false;
		chatHistory = [
			{
				role: "assistant",
				content:
					"Describe the new Spring Boot + Svelte project you want to build.",
			},
		];
	}

	function toggleVersionHistory() {
		showVersionHistory = !showVersionHistory;
		if (showVersionHistory) {
			isCodeViewCollapsed = true;
		}
	}

	function handleVersionRestore(checkpointId: string) {
		showVersionHistory = false;
		if (activeProjectId) {
			loadChatHistory(activeProjectId);
			warmupAndLoadFiles(activeProjectId);
		}
	}

	async function switchProject(projectId: string) {
		if (aguiClient) {
			aguiClient.disconnect();
		}
		activeProjectId = projectId;
		localStorage.setItem("chorus.activeProjectId", projectId);
		await restoreProjectSession(projectId);
	}

	async function deleteProject(projectId: string) {
		const res = await fetch(`/api/projects/${projectId}`, {
			method: "DELETE",
		});
		if (!res.ok) {
			const err = await res.json().catch(() => ({}));
			throw new Error(err.error || "Failed to delete project");
		}
		// If the deleted project was active, clear state
		if (activeProjectId === projectId) {
			activeProjectId = null;
			localStorage.removeItem("chorus.activeProjectId");
			if (aguiClient) {
				aguiClient.disconnect();
			}
			resetProjectViewState();
			chatHistory = [
				{
					role: "assistant",
					content:
						"Welcome! I can generate full Spring Boot + Svelte projects from your description. What would you like to build?",
				},
			];
		}
	}

	async function warmupAndLoadFiles(projectId: string) {
		try {
			const warmupRes = await fetch(
				`/api/workspace/${projectId}/warmup`,
				{ method: "POST" },
			);
			if (warmupRes.ok) {
				const warmupData = await warmupRes.json();
				console.log("[workspace] Warmup status:", warmupData.status);
			}
		} catch (e) {
			console.error("Failed to warmup workspace:", e);
		}

		if (!isCodeViewCollapsed) {
			loadWorkspaceFiles(projectId);
		}
	}

	async function loadChatHistory(projectId: string) {
		try {
			const res = await fetch(`/api/projects/${projectId}/messages`);
			if (res.ok) {
				const data = await res.json();
				if (data.messages && data.messages.length > 0) {
					chatHistory = data.messages.map((m: any) => ({
						role: m.role,
						content: m.content,
						metadata: m.metadata,
					}));
				} else {
					chatHistory = [];
				}
			}
		} catch (e) {
			console.error("Failed to load chat history:", e);
			chatHistory = [];
		}
	}

	async function loadWorkspaceFiles(projectId: string) {
		const requestSeq = ++_workspaceLoadSeq;
		try {
			const res = await fetch(`/api/workspace/${projectId}/files`);
			if (requestSeq !== _workspaceLoadSeq || activeProjectId !== projectId) {
				return;
			}
			if (res.ok) {
				const data = await res.json();
				if (requestSeq !== _workspaceLoadSeq || activeProjectId !== projectId) {
					return;
				}
				workspaceFiles = data.files || [];
			}
		} catch (e) {
			if (requestSeq !== _workspaceLoadSeq || activeProjectId !== projectId) {
				return;
			}
			console.error("Failed to load workspace files:", e);
		}
	}

	function scheduleFileTreeRefresh(projectId: string) {
		if (_fileRefreshTimer) clearTimeout(_fileRefreshTimer);
		_fileRefreshTimer = setTimeout(() => {
			if (activeProjectId === projectId) loadWorkspaceFiles(projectId);
		}, 600);
	}

	function toggleCodeView() {
		isCodeViewCollapsed = !isCodeViewCollapsed;
		if (!isCodeViewCollapsed) {
			showVersionHistory = false;
		}
		if (!isCodeViewCollapsed && activeProjectId) {
			warmupAndLoadFiles(activeProjectId);
		}
	}

	onMount(() => {
		agentRegistry.initialize();

		const checkMobile = () => {
			isMobile = window.innerWidth < 768;
			if (isMobile) isSidebarCollapsed = true;
		};
		checkMobile();
		window.addEventListener("resize", checkMobile);

		// Only show welcome message on page load - user must explicitly select a project to resume
		chatHistory = [
			{
				role: "assistant",
				content:
					"Welcome! I can generate full Spring Boot + Svelte projects from your description. What would you like to build?",
			},
		];

		const savedProjectId = localStorage.getItem("chorus.activeProjectId");
		if (savedProjectId) {
			activeProjectId = savedProjectId;
			void restoreProjectSession(savedProjectId);
		}

		return () => window.removeEventListener("resize", checkMobile);
	});

	onDestroy(() => {
		if (_fileRefreshTimer) {
			clearTimeout(_fileRefreshTimer);
		}
		if (aguiClient) {
			aguiClient.disconnect();
		}
	});

	// === Design helpers & additional state ===
	let agentDetailTab = $state<'timeline' | 'thinking' | 'tools' | 'tasks'>('timeline');
	let sidebarSearchQuery = $state('');
	let showDirectInput = $state(false);
	let directMessage = $state('');

	function getAgentGlyph(agentId: string): string {
		const map: Record<string, string> = {
			'agent-rootdep': 'RT', 'agent-backend': 'BE', 'agent-frontend': 'FE',
			'agent-devops': 'OP', 'agent-packager': 'PK',
		};
		return map[agentId] || agentId.replace('agent-', '').slice(0, 2).toUpperCase();
	}
	function getAgentShortName(agentId: string): string {
		const map: Record<string, string> = {
			'agent-rootdep': 'root', 'agent-backend': 'back', 'agent-frontend': 'front',
			'agent-devops': 'ops', 'agent-packager': 'pack',
		};
		return map[agentId] || agentId.replace('agent-', '');
	}
	function getAgentRole(agentId: string): string {
		const map: Record<string, string> = {
			'agent-rootdep': 'PLANNER', 'agent-backend': 'SPRING', 'agent-frontend': 'SVELTE 5',
			'agent-devops': 'DOCKER · CI', 'agent-packager': 'BUILD',
		};
		return map[agentId] || 'AGENT';
	}
	function getAgentHue(agentId: string): string {
		const map: Record<string, string> = {
			'agent-rootdep': 'violet', 'agent-backend': 'amber', 'agent-frontend': 'cyan',
			'agent-devops': 'green', 'agent-packager': 'rose',
		};
		return map[agentId] || '';
	}
	function getStatusLabel(status: string): string {
		const map: Record<string, string> = {
			'working': 'RUN', 'thinking': 'RUN', 'complete': 'DONE',
			'idle': 'IDLE', 'error': 'REVIEW', 'paused': 'QUEUED', 'stopped': 'IDLE',
		};
		return map[status] || status.toUpperCase();
	}
	function getStatusClass(status: string): string {
		const map: Record<string, string> = {
			'working': 'st run', 'thinking': 'st run', 'complete': 'st done',
			'idle': 'st idle', 'error': 'st review', 'paused': 'st queue', 'stopped': 'st idle',
		};
		return map[status] || 'st idle';
	}
	function formatTime(ts: number): string {
		return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}
	function stripThinkTags(content: string): string {
		return content.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
	}
	function extractJsonFromOutput(output: any): any {
		if (!output) return null;
		if (typeof output !== 'string') return output;
		const contentMatch = output.match(/content='(.+)'/s);
		if (contentMatch) {
			try { return JSON.parse(contentMatch[1]); } catch { /* fall through */ }
			try { return JSON.parse(contentMatch[1].replace(/\\'/g, "'")); } catch { /* fall through */ }
		}
		try { return JSON.parse(output); } catch { /* fall through */ }
		return null;
	}
	type ToolView = {
		name: string;
		phase: 'starting' | 'completed' | 'failed' | 'event';
		title: string;
		subtitle: string;
		subtitleTitle?: string;
		rows: { label: string; value: string; title: string }[];
		items: { label: string; title: string }[];
		preview?: string;
		previewTitle?: string;
		previewKind?: 'code' | 'text';
	};

	function humanizeToolName(raw: string): string {
		return raw
			.replace(/^file\./, '')
			.replace(/_/g, ' ')
			.replace(/\b\w/g, (m) => m.toUpperCase());
	}

	function getToolName(event: { type: string; data?: any }): string {
		return String(event.data?.tool || event.type || 'tool');
	}

	function getToolInput(event: { data?: any }): any {
		return event.data?.input || event.data?.args || event.data?.arguments || null;
	}

	function clipText(value: string, max = 220): string {
		return value.length > max ? `${value.slice(0, max).trimEnd()}...` : value;
	}

	function stringifyToolValue(value: any, max = 120): { value: string; title: string } {
		if (value === null || value === undefined) return { value: '', title: '' };
		if (typeof value === 'string') return { value: clipText(value, max), title: value };
		if (typeof value === 'number' || typeof value === 'boolean') {
			const text = String(value);
			return { value: text, title: text };
		}
		try {
			const title = JSON.stringify(value, null, 2);
			if (Array.isArray(value)) {
				return { value: `${value.length} item${value.length === 1 ? '' : 's'}`, title };
			}
			const summarizeNested = (nested: any): string => {
				if (nested === null || nested === undefined) return '';
				if (typeof nested === 'string' || typeof nested === 'number' || typeof nested === 'boolean') return String(nested);
				if (Array.isArray(nested)) return `${nested.length} item${nested.length === 1 ? '' : 's'}`;
				if (typeof nested === 'object') {
					const nestedKeys = Object.keys(nested);
					if (nestedKeys.length === 0) return '{}';
					return `{ ${nestedKeys.slice(0, 2).join(', ')}${nestedKeys.length > 2 ? ', ...' : ''} }`;
				}
				return String(nested);
			};
			const keys = Object.keys(value);
			const summary = keys.length > 0
				? keys.slice(0, 3).map((key) => `${key}: ${clipText(summarizeNested(value[key]), 28)}`).join(', ')
				: '{}';
			const suffix = keys.length > 3 ? `, +${keys.length - 3} more` : '';
			return { value: clipText(`${summary}${suffix}`, max), title };
		} catch {
			const text = String(value);
			return { value: clipText(text, max), title: text };
		}
	}

	function previewLines(content: string, maxLines = 8): string {
		const lines = content.split(/\r?\n/);
		const preview = lines.slice(0, maxLines);
		if (lines.length > maxLines) preview.push(`... ${lines.length - maxLines} more lines`);
		return preview.join('\n');
	}

	function formatToolView(event: { type: string; content?: string; data?: any }): ToolView | null {
		const tool = getToolName(event);
		const input = getToolInput(event);
		const output = extractJsonFromOutput(event.data?.output);
		const isStart = event.type === 'tool_start';
		const failed = output?.status === 'error' || Boolean(output?.error);
		const phase: ToolView['phase'] = isStart ? 'starting' : failed ? 'failed' : event.type.includes('tool') ? 'completed' : 'event';
		const rows: ToolView['rows'] = [];
		let subtitle = isStart ? 'Preparing input' : 'Finished';
		let subtitleTitle: string | undefined;
		let title = humanizeToolName(tool);
		let items: ToolView['items'] = [];
		let preview: string | undefined;
		let previewTitle: string | undefined;
		let previewKind: ToolView['previewKind'];

		if (input && typeof input === 'object') {
			for (const [key, value] of Object.entries(input).slice(0, 4)) {
				const formatted = stringifyToolValue(value, 120);
				rows.push({ label: humanizeToolName(key), value: formatted.value, title: formatted.title });
			}
		}

		if (output && typeof output === 'object') {
			const status = String(output.status || (failed ? 'error' : 'success'));
			rows.unshift({ label: 'Status', value: status, title: status });

			if (tool === 'read_file') {
				const path = String(output.file_path || input?.file_path || '');
				const content = String(output.content || '');
				const lines = content ? content.split(/\r?\n/).length : 0;
				title = 'Read File';
				subtitle = path || 'Workspace file';
				subtitleTitle = subtitle;
				rows.push({ label: 'Lines', value: String(lines), title: String(lines) });
				rows.push({ label: 'Characters', value: String(content.length), title: String(content.length) });
				if (content) {
					preview = previewLines(content);
					previewTitle = content;
					previewKind = 'code';
				}
			} else if (tool === 'list_files') {
				const files = Array.isArray(output.files) ? output.files : [];
				title = 'List Files';
				subtitle = output.directory ? `Directory: ${output.directory}` : 'Workspace root';
				subtitleTitle = subtitle;
				rows.push({ label: 'Files', value: String(files.length), title: String(files.length) });
				items = files.slice(0, 12).map((file: any) => {
					const title = String(file);
					return { label: clipText(title, 80), title };
				});
				if (files.length > 12) items.push({ label: `+${files.length - 12} more`, title: files.slice(12).map(String).join('\n') });
			} else if (tool === 'write_file' || tool === 'file.write') {
				title = 'Write File';
				subtitle = String(output.file_path || input?.file_path || 'Workspace file');
				subtitleTitle = subtitle;
				if (output.bytes_written !== undefined) rows.push({ label: 'Bytes', value: String(output.bytes_written), title: String(output.bytes_written) });
			} else if (tool === 'web_search') {
				const results = Array.isArray(output.results) ? output.results : [];
				title = 'Web Search';
				subtitle = String(output.query || input?.query || 'Search');
				subtitleTitle = subtitle;
				rows.push({ label: 'Results', value: String(output.count || results.length), title: String(output.count || results.length) });
				items = results.slice(0, 5).map((r: any) => {
					const text = String(r.title || r.url || 'Untitled result');
					const title = [text, r.snippet, r.url].filter(Boolean).join('\n');
					return { label: clipText(text, 80), title };
				});
			} else if (output.message || output.error) {
				subtitle = String(output.message || output.error);
				subtitleTitle = subtitle;
			}
		} else if (isStart && tool === 'read_file' && input?.file_path) {
			title = 'Read File';
			subtitle = String(input.file_path);
			subtitleTitle = subtitle;
		} else if (isStart && tool === 'list_files') {
			title = 'List Files';
			subtitle = input?.directory ? `Directory: ${input.directory}` : 'Workspace root';
			subtitleTitle = subtitle;
		} else if (event.content) {
			const clean = stripThinkTags(event.content);
			subtitle = clipText(clean, 160);
			subtitleTitle = clean;
		}

		if (!event.data && !event.content) return null;
		return { name: humanizeToolName(tool), phase, title, subtitle, subtitleTitle, rows, items, preview, previewTitle, previewKind };
	}

	function formatToolSummary(tool: { type: string; content?: string; data?: any }): string {
		const parsed = extractJsonFromOutput(tool.data?.output);
		if (!parsed) return tool.content || '';
		if (parsed.status === 'success') {
			if (tool.type === 'web_search') {
				return `${parsed.query || 'Search'} · ${parsed.count || 0} results`;
			}
			if (tool.type === 'read_file') {
				const lines = (parsed.content || '').split('\n').length;
				return `${parsed.file_path || ''} · ${lines} lines`;
			}
			if (tool.type === 'file.write' || tool.type === 'write_file') {
				return `${parsed.file_path || ''} · written`;
			}
			if (tool.type === 'update_todo_status') {
				return `Todo #${(parsed.index ?? 0) + 1} → ${parsed.new_status || 'updated'}`;
			}
			if (tool.type === 'write_todos') {
				const done = parsed.completed ?? parsed.todos?.filter((t: any) => t.status === 'completed').length ?? 0;
				const total = parsed.todos_count ?? parsed.todos?.length ?? 0;
				return `${total} tasks · ${done} done`;
			}
			if (tool.type === 'list_files') {
				const count = parsed.files?.length ?? 0;
				return `${parsed.directory || ''} · ${count} files`;
			}
			if (parsed.formatted) return parsed.formatted;
		}
		return tool.content || '';
	}
	function parseToolDetails(tool: { type: string; content?: string; data?: any }): { kind: string; items: { label: string; status?: string; meta?: string }[]; meta?: string } | null {
		const parsed = extractJsonFromOutput(tool.data?.output);
		if (!parsed || parsed.status !== 'success') return null;
		if (tool.type === 'write_todos' || tool.type === 'update_todo_status') {
			const todos = parsed.todos || [];
			const done = parsed.completed ?? todos.filter((t: any) => t.status === 'completed').length;
			const total = parsed.todos_count ?? todos.length;
			return {
				kind: 'todos',
				items: todos.map((t: any) => ({ label: t.content || t.name || '', status: t.status })),
				meta: `${done}/${total} completed`,
			};
		}
		if (tool.type === 'web_search') {
			const results = parsed.results || [];
			return {
				kind: 'search',
				items: results.slice(0, 3).map((r: any) => ({ label: r.title || '', meta: r.snippet?.slice(0, 80) || '' })),
				meta: `${parsed.count || results.length} results`,
			};
		}
		if (tool.type === 'read_file') {
			const lines = (parsed.content || '').split('\n').length;
			return {
				kind: 'file',
				items: [{ label: parsed.file_path || '', meta: `${lines} lines` }],
			};
		}
		if (tool.type === 'file.write' || tool.type === 'write_file') {
			return {
				kind: 'file',
				items: [{ label: parsed.file_path || '', meta: 'written' }],
			};
		}
		if (tool.type === 'list_files') {
			const files = parsed.files || [];
			return {
				kind: 'file',
				items: files.slice(0, 8).map((f: string) => ({ label: f, meta: '' })),
				meta: files.length > 8 ? `+${files.length - 8} more` : `${files.length} files`,
			};
		}
		return null;
	}
	function formatToolDataForPane(tool: { type: string; content?: string; data?: any }): { lines: string[]; isCode: boolean } | null {
		const parsed = extractJsonFromOutput(tool.data?.output);
		if (!parsed) return null;
		if (parsed.status !== 'success') return null;

		if (tool.type === 'read_file') {
			const content = parsed.content || '';
			const lines = content.split('\n');
			const preview = lines.slice(0, 12);
			if (lines.length > 12) preview.push(`... ${lines.length - 12} more lines`);
			return { lines: [`📄 ${parsed.file_path || ''}`, ...preview], isCode: true };
		}
		if (tool.type === 'list_files') {
			const files = parsed.files || [];
			const preview = files.slice(0, 10);
			const rest = files.length > 10 ? [`... ${files.length - 10} more files`] : [];
			return { lines: [`📁 ${parsed.directory || ''} · ${files.length} files`, ...preview, ...rest], isCode: false };
		}
		if (tool.type === 'web_search') {
			const results = parsed.results || [];
			const lines = [`🔍 ${parsed.query || 'Search'} · ${parsed.count || results.length} results`];
			results.slice(0, 3).forEach((r: any, i: number) => {
				lines.push(`${i + 1}. ${r.title || ''}`);
				if (r.snippet) lines.push(`   ${r.snippet.slice(0, 100)}${r.snippet.length > 100 ? '...' : ''}`);
			});
			return { lines, isCode: false };
		}
		if (tool.type === 'write_todos' || tool.type === 'update_todo_status') {
			const todos = parsed.todos || [];
			const lines = todos.map((t: any) => `${t.status === 'completed' ? '✓' : '○'} ${t.content || t.name || ''}`);
			return { lines, isCode: false };
		}
		if (tool.type === 'file.write' || tool.type === 'write_file') {
			return { lines: [`✏️ ${parsed.file_path || ''}`], isCode: false };
		}
		if (tool.type === 'list_api_endpoints') {
			const endpoints = parsed.endpoints || [];
			const lines = [`🔌 ${parsed.count || endpoints.length} API endpoints available`];
			endpoints.slice(0, 6).forEach((ep: any) => {
				lines.push(`  ${ep.method || ''} ${ep.path || ''}`);
			});
			if (endpoints.length > 6) lines.push(`  ... +${endpoints.length - 6} more`);
			return { lines, isCode: false };
		}
		return null;
	}
	function formatStructuredToolData(data: any): string | null {
		if (!data || typeof data !== 'object') return null;
		if (data.status && typeof data.status === 'string') {
			const parts: string[] = [];
			parts.push(`Status: ${data.status}`);
			if (data.message) parts.push(`Message: ${data.message}`);
			if (data.error) parts.push(`Error: ${data.error}`);
			if (data.result !== undefined) parts.push(`Result: ${JSON.stringify(data.result).slice(0, 200)}`);
			return parts.join('\n');
		}
		if (data.output && typeof data.output === 'string') {
			const parsed = extractJsonFromOutput(data.output);
			if (parsed && parsed.status) {
				return formatStructuredToolData(parsed);
			}
		}
		return null;
	}
	function truncateJson(obj: any, maxLen: number = 600): string {
		const str = JSON.stringify(obj, null, 2);
		if (str.length <= maxLen) return str;
		return str.slice(0, maxLen) + '\n... (truncated)';
	}
	function parseChatSource(content: string): { source: string; text: string } {
		const cleaned = stripThinkTags(content);
		const match = cleaned.match(/^\[([^\]]+)\]:\s*(.*)$/s);
		if (match) {
			return { source: match[1], text: match[2] };
		}
		return { source: 'Chorus', text: cleaned };
	}
	function getChatGlyph(content: string): string {
		const parsed = parseChatSource(content);
		if (parsed.source === 'Chorus' || parsed.source === 'Agent') return 'CH';
		const agent = allAgents.find(a =>
			a.name.toLowerCase().includes(parsed.source.toLowerCase()) ||
			parsed.source.toLowerCase().includes(a.name.toLowerCase()) ||
			a.id === `agent-${parsed.source.toLowerCase().replace(/\s+/g, '')}`
		);
		if (agent) return getAgentGlyph(agent.id);
		return parsed.source.slice(0, 2).toUpperCase();
	}
</script>

<div class="app">
	<svg width="0" height="0" style="position: absolute;">
		<defs>
			<linearGradient id="g-vio" x1="0%" y1="0%" x2="100%" y2="100%">
				<stop offset="0%" stop-color="oklch(70% 0.18 295)" />
				<stop offset="100%" stop-color="oklch(60% 0.22 280)" />
			</linearGradient>
		</defs>
	</svg>

	<!-- SIDEBAR -->
	<ProjectSidebar
		{activeProjectId}
		isCollapsed={isSidebarCollapsed}
		{isMobile}
		onToggle={() => (isSidebarCollapsed = !isSidebarCollapsed)}
		onSelect={switchProject}
		onNew={startNewProject}
		onDelete={deleteProject}
	/>

	<!-- CENTER STAGE -->
	<section class="stage">
		<header class="topbar">
			{#if isMobile && isSidebarCollapsed}
				<button class="ico-btn" onclick={() => (isSidebarCollapsed = false)} title="Open sidebar">
					<PanelLeftOpen class="h-4 w-4" />
				</button>
			{/if}

			<div class="crumb">
				<span>WORKSPACE</span>
				{#if activeProjectId}
					<ChevronRight size={10} />
					<b>{activeProjectId.slice(0, 8).toUpperCase()}</b>
				{/if}
			</div>

			{#if isRunning}
				<span class="running-pill">
					<span class="dot"></span>
					{agentRegistry.activeAgents.length} AGENT{agentRegistry.activeAgents.length === 1 ? '' : 'S'} · CONDUCTING
				</span>
			{/if}

			<div class="seg">
				<button class={!isPlanMode ? 'on' : ''} onclick={() => setPlanMode(false)}>
					<Hexagon class="h-3.5 w-3.5" />
					Build
				</button>
				<button class={isPlanMode ? 'on' : ''} onclick={() => setPlanMode(true)}>
					<Map class="h-3.5 w-3.5" />
					Plan
				</button>
			</div>

			{#if activeProjectId}
				<button class="ico-btn" title="Version history" onclick={toggleVersionHistory}>
					<History class="h-4 w-4" />
				</button>
				<button class="ico-btn" title="Code view" onclick={toggleCodeView}>
					<Code2 class="h-4 w-4" />
				</button>
			{/if}

			{#if isRunning}
				<button class="ico-btn" title="Stop swarm" style="color: var(--rose);" onclick={handleStopSwarm}>
					<Square class="h-4 w-4 fill-current" />
				</button>
			{/if}
		</header>

		<div class="scroll">
			<div class="frame">
				<!-- Project Header -->
				<div class="proj-head">
					<span class="eyebrow">
						{#if activeProjectId}
							A ── {activeProjectId.slice(0, 8).toUpperCase()}
						{:else}
							CHORUS
						{/if}
					</span>
					<h1>
						{#if !activeProjectId && !isPlanMode}
							What would you like to <em>build?</em>
						{:else if isPlanMode}
							Planning mode <em>activated</em><br/>Create a detailed implementation plan.
						{:else}
							{#if chatHistory.find(m => m.role === 'user')}
								{@const firstUser = chatHistory.find(m => m.role === 'user')}
								{firstUser?.content?.slice(0, 60) || 'Project'}{firstUser && firstUser.content.length > 60 ? '...' : ''}
							{:else}
								Active project
							{/if}
						{/if}
					</h1>
					<div class="meta-row">
						{#if activeProjectId}
							<span>STATUS · <b>{isRunning ? 'RUNNING' : 'IDLE'}</b></span>
							<span>AGENTS · <b>{allAgents.length}</b></span>
							<span>FILES · <b>{workspaceFiles.length}</b></span>
						{:else}
							<span>READY · <b>START</b></span>
						{/if}
					</div>
				</div>

				<!-- Error banner -->
				{#if hasError}
					<div style="margin-bottom: 20px; padding: 12px 16px; border-radius: 12px; background: oklch(95% 0.05 25); border: 1px solid oklch(85% 0.12 25); color: var(--rose); font-size: 13px;">
						<b>Error:</b> {errorMessage}
					</div>
				{/if}

				<!-- Plan Mode -->
				{#if isPlanMode && (hasPlanTelemetry || isExecutingPlan || Boolean(planResponse) || Boolean(specContent))}
					<PlanActivityPanel
						agents={planAgents}
						isStreaming={isExecutingPlan || isRunning}
						hasSpec={Boolean(specContent)}
						statusLabel={planActivityStatusLabel}
					/>
				{/if}

				{#if specContent}
					<div class="mesh-card" style="margin-top: 24px;">
						<header>
							<h3>SPEC.md <small>{planMetrics.lines} LINES · {planMetrics.words} WORDS</small></h3>
							<div style="display: flex; gap: 8px;">
								{#if isEditingSpec}
									<Button variant="outline" size="sm" onclick={handleCancelEditSpec}>Cancel</Button>
									<Button size="sm" onclick={handleSaveSpec}>Save</Button>
								{:else}
									<Button variant="outline" size="sm" onclick={handleEditSpec}>Edit</Button>
								{/if}
							</div>
						</header>
						{#if isEditingSpec}
							<div style="display: grid; gap: 16px; grid-template-columns: 1fr 1fr;">
								<textarea
									bind:value={editedSpecContent}
									style="width: 100%; height: 400px; resize: none; border-radius: 12px; border: 1px solid var(--line); background: var(--paper-1); padding: 12px; font-family: var(--font-mono); font-size: 12px; line-height: 1.6; color: var(--ink-0); outline: none;"
									placeholder="Edit SPEC.md content..."
								></textarea>
								<div style="height: 400px; overflow-y: auto; border-radius: 12px; border: 1px solid var(--line); background: var(--paper-0); padding: 16px;">
									<PlanSpecPreview source={editedSpecContent} />
								</div>
							</div>
						{:else}
							<div style="max-height: 560px; overflow-y: auto; border-radius: 12px; border: 1px solid var(--line); background: var(--paper-0); padding: 16px;">
								<PlanSpecPreview source={editedSpecContent || specContent} />
							</div>
						{/if}
						<div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line); display: flex; justify-content: space-between; align-items: center;">
							<span style="font-size: 12.5px; color: var(--ink-4);">Review the plan before execution.</span>
							<div style="display: flex; gap: 8px;">
								<Button variant="outline" onclick={() => { specContent = null; editedSpecContent = ''; planResponse = null; isEditingSpec = false; }}>Discard</Button>
								<Button onclick={handleExecutePlan} disabled={isExecutingPlan || isRunning}>
									{#if isExecutingPlan}
										<Loader2 class="h-4 w-4 animate-spin mr-2" />
									{:else}
										<Play class="h-4 w-4 mr-2" />
									{/if}
									Approve & Execute
								</Button>
							</div>
						</div>
					</div>
				{/if}

				<!-- Build Mode -->
				{#if !isPlanMode}
					<!-- Mesh Grid -->
					<div class="mesh-card">
						<header>
							<h3>Mesh state <small>SWARM · {allAgents.length} agents</small></h3>
							<div class="legend">
								<span><i style="background: var(--violet)"></i> ACTIVE</span>
								<span><i style="background: var(--ink-5)"></i> IDLE</span>
							</div>
						</header>
						<div class="mesh-grid">
							{#each allAgents as agent}
								<button
									class="agent {agent.status !== 'idle' ? 'active' : ''} {agent.id === agentRegistry.selectedAgentId ? 'selected' : ''}"
									data-h={getAgentHue(agent.id)}
									onclick={() => agentRegistry.selectAgent(agent.id)}
									type="button"
								>
									<div class="row">
										<span class="glyph">{getAgentGlyph(agent.id)}</span>
										<div class="nm">
											{getAgentShortName(agent.id)}
											<small>{getAgentRole(agent.id)}</small>
										</div>
										<span class="st {getStatusClass(agent.status)}">{getStatusLabel(agent.status)}</span>
									</div>
									<div class="bar">
										{#if agent.status === 'idle' || agent.status === 'stopped'}
											<div style="animation: none; width: {agent.progress?.percent || 0}%;"></div>
										{:else}
											<div></div>
										{/if}
									</div>
									<div class="meta">
										<span>{agent.currentAction || (agent.tasks.length > 0 ? agent.tasks[0].name : '—')}</span>
										<span>{agent.progress?.completed || 0}/{agent.progress?.total || 0}</span>
									</div>
								</button>
							{/each}
						</div>
					</div>

					<!-- Chat -->
					<div class="chat">
						{#each chatHistory as message, index (index)}
							{#if message.role === 'user'}
								<div class="msg user">
									<span class="av-m">YOU</span>
									<div class="bub">
										<MarkdownContent source={stripThinkTags(message.content)} />
									</div>
								</div>
							{:else}
								{@const parsed = parseChatSource(message.content)}
								<div class="msg assistant">
									<span class="av-m">{getChatGlyph(message.content)}</span>
									<div class="bub">
										{#if parsed.source !== 'Chorus'}
											<div class="src">{parsed.source}</div>
										{/if}
										<MarkdownContent source={parsed.text} />
										{#if message.tools && message.tools.length > 0}
											{#each message.tools as tool}
												{@const details = parseToolDetails(tool)}
												<div class="tool-card">
													<div class="tool-head">
														<span class="tag">{tool.type}</span>
														<span class="tool-summary">{formatToolSummary(tool)}</span>
													</div>
													{#if details}
														<div class="tool-details {details.kind}">
															{#each details.items as item}
																<div class="tool-row">
																	{#if details.kind === 'todos'}
																		<span class="td-check {item.status === 'completed' ? 'done' : ''}">{item.status === 'completed' ? '✓' : '○'}</span>
																	{/if}
																	<span class="td-label {item.status === 'completed' ? 'done' : ''}">{item.label}</span>
																	{#if item.meta}
																		<span class="td-meta">{item.meta}</span>
																	{/if}
																</div>
															{/each}
															{#if details.meta}
																<div class="tool-meta">{details.meta}</div>
															{/if}
														</div>
													{/if}
												</div>
											{/each}
										{/if}
									</div>
								</div>
							{/if}
						{/each}
					</div>
				{/if}

				<!-- Download -->
				{#if downloadReady && downloadData}
					<div style="margin-top: 28px;">
						<DownloadButtons
							projectName={downloadData.project_name}
							projectId={downloadData.project_id}
							zipUrl={downloadData.zip_url}
							downloadUrl={downloadData.download_url}
						/>
					</div>
				{/if}
			</div>

			<!-- Question Card -->
			{#if pendingQuestion}
				<div class="question-wrap">
					<Card.Root class="question-panel">
						<Card.Header class="question-head">
							<span class="question-kicker">ROOT · FOLLOW-UP</span>
							<Card.Title class="question-title">{isPlanMode ? 'Lock the planning preferences' : 'Answer to continue'}</Card.Title>
							<Card.Description class="question-description">{isPlanMode ? 'These answers are sent back to the planner and saved with the project preference context.' : 'The running agent is paused until these answers are submitted.'}</Card.Description>
						</Card.Header>

						<Card.Content class="question-list">
							{#each pendingQuestion.questions as question, i}
								<div class="question-item">
									<div class="question-label-row">
										<label for={`agent-question-${i}`}>{question.label}</label>
										<span>{question.type.replace('_', ' ')}</span>
									</div>
									{#if question.help}
										<p class="question-help">{question.help}</p>
									{/if}

									{#if question.type === 'single_select' || question.type === 'boolean'}
										<div class="question-options">
											{#each (question.options.length ? question.options : ['Yes', 'No']) as option}
												<Button
													type="button"
													variant="outline"
													size="sm"
													class={questionAnswers[i] === option ? 'question-option selected' : 'question-option'}
													onclick={() => setQuestionAnswer(i, option)}
												>
													{option}
												</Button>
											{/each}
										</div>
										<Input
											id={`agent-question-${i}`}
											class="question-input"
											value={questionAnswers[i]}
											oninput={(e) => setQuestionAnswer(i, e.currentTarget.value)}
											placeholder="Or type a custom preference..."
										/>
									{:else if question.type === 'multi_select'}
										<div class="question-options multi">
											{#each question.options as option}
												<Button
													type="button"
													variant="outline"
													size="sm"
													class={selectedMultiValues(i).includes(option) ? 'question-option selected' : 'question-option'}
													onclick={() => toggleMultiAnswer(i, option)}
												>
													{option}
												</Button>
											{/each}
										</div>
										<Input
											id={`agent-question-${i}`}
											class="question-input"
											value={questionAnswers[i]}
											oninput={(e) => setQuestionAnswer(i, e.currentTarget.value)}
											placeholder="Selected values or custom answer..."
										/>
									{:else if question.type === 'textarea'}
										<Textarea
											id={`agent-question-${i}`}
											class="question-textarea"
											value={questionAnswers[i]}
											oninput={(e) => setQuestionAnswer(i, e.currentTarget.value)}
											placeholder="Add the details the planner should preserve..."
											rows={4}
										/>
									{:else}
										<Input
											id={`agent-question-${i}`}
											class="question-input"
											value={questionAnswers[i]}
											oninput={(e) => setQuestionAnswer(i, e.currentTarget.value)}
											placeholder="Your answer..."
										/>
									{/if}
								</div>
							{/each}
						</Card.Content>

						<Card.Footer class="question-actions">
							<span class="question-count">{pendingQuestion.questions.length} preference{pendingQuestion.questions.length === 1 ? '' : 's'} requested</span>
							<Button
								type="button"
								class="question-submit"
								onclick={submitAnswers}
								disabled={isSubmittingAnswers || !canSubmitPendingQuestion()}
							>
								{#if isSubmittingAnswers}
									<Loader2 size={14} class="animate-spin" />
								{:else}
									<ArrowRight size={13} />
								{/if}
								Submit
							</Button>
						</Card.Footer>
					</Card.Root>
				</div>
			{/if}
		</div>

		<!-- Composer -->
		<div class="composer-wrap">
			<div class="quick">
				<button type="button" onclick={() => inputValue = 'Build a task manager with Spring Boot and Svelte'}>
					<span>01</span> Task manager
				</button>
				<button type="button" onclick={() => inputValue = 'Add Stripe billing and user authentication'}>
					<span>02</span> Stripe billing
				</button>
				<button type="button" onclick={() => inputValue = 'Create a REST API with CRUD operations'}>
					<span>03</span> REST API
				</button>
			</div>
			<form
				class="composer"
				onsubmit={(e: Event) => {
					e.preventDefault();
					handleSubmit();
				}}
			>
				<textarea
					bind:value={inputValue}
					placeholder={activeProjectId
						? "Ask for a modification... (e.g., Add Stripe billing and an admin dashboard)"
						: "Describe your project... (e.g., Build a task manager with Spring Boot and Svelte)"}
					disabled={isRunning}
					rows="1"
					onkeydown={(e: KeyboardEvent) => {
						if (e.key === 'Enter' && !e.shiftKey) {
							e.preventDefault();
							handleSubmit();
						}
					}}
				></textarea>
				<div class="composer-foot">
					<span class="chip on">
						<Hexagon size={13} />
						<span class="l">BUILD</span>
					</span>
					<span class="chip">
						<Eye size={13} />
						AUTO-CTX
					</span>
					<span class="chip">
						<MessageSquare size={13} />
						@ROOT
					</span>
					<button type="submit" class="send" disabled={isRunning || !inputValue.trim()}>
						{#if isRunning}
							<Loader2 size={16} class="animate-spin" />
						{:else}
							<span>Send</span>
							<ArrowRight size={13} />
							<kbd>⏎</kbd>
						{/if}
					</button>
				</div>
			</form>
		</div>
	</section>

	<!-- RIGHT PANEL -->
	{#if !isCodeViewCollapsed && activeProjectId}
		<aside class="agent-pane code-pane">
			<CodeView
				files={workspaceFiles}
				projectId={activeProjectId}
				collapsed={isCodeViewCollapsed}
				onToggleCollapse={toggleCodeView}
				onSelectAgent={(id) => agentRegistry.selectAgent(id)}
				selectedAgentId={agentRegistry.selectedAgentId}
				agents={allAgents}
				{lastWrittenFile}
			/>
		</aside>
	{:else if showVersionHistory && activeProjectId}
		<aside class="agent-pane" style="width: 520px;">
			<VersionHistory
				projectId={activeProjectId}
				onClose={() => (showVersionHistory = false)}
				onRestore={handleVersionRestore}
			/>
		</aside>
	{:else if selectedAgent && !isPlanMode}
		<aside class="agent-pane">
			<div class="ap-head">
				<span class="ix">AGENT · DETAIL</span>
				<h3>{getAgentShortName(selectedAgent.id)} <em>· {getAgentRole(selectedAgent.id).toLowerCase()}</em></h3>
				<span class="role">{getAgentRole(selectedAgent.id)}</span>
				<div class="stat-row">
					<div class="stat-cell">
						<div class="l">EVENTS</div>
						<div class="v">{selectedAgent.events.length}</div>
					</div>
					<div class="stat-cell">
						<div class="l">STEPS</div>
						<div class="v">{selectedAgent.progress?.percent || 0}<em>%</em></div>
					</div>
					<div class="stat-cell">
						<div class="l">TOOLS</div>
						<div class="v">{selectedAgent.toolCalls.length}</div>
					</div>
				</div>
			</div>

			<nav class="ap-tabs">
				<button class={agentDetailTab === 'timeline' ? 'on' : ''} onclick={() => agentDetailTab = 'timeline'}>
					Timeline <span class="c">{selectedAgent.events.length}</span>
				</button>
				<button class={agentDetailTab === 'thinking' ? 'on' : ''} onclick={() => agentDetailTab = 'thinking'}>
					Thinking
				</button>
				<button class={agentDetailTab === 'tools' ? 'on' : ''} onclick={() => agentDetailTab = 'tools'}>
					Tools <span class="c">{selectedAgent.toolCalls.length}</span>
				</button>
				<button class={agentDetailTab === 'tasks' ? 'on' : ''} onclick={() => agentDetailTab = 'tasks'}>
					Tasks <span class="c">{selectedAgent.tasks.filter(t => t.completed).length}/{selectedAgent.tasks.length}</span>
				</button>
			</nav>

			<div class="ap-body" bind:this={agentDetailBody} onscroll={handleAgentDetailScroll}>
				{#if agentDetailTab === 'timeline'}
					{@const displayEvents = selectedAgent.events.filter(e => e.type !== 'thinking' && e.type !== 'reasoning').reverse()}
					<div class="timeline">
						{#each displayEvents as event, i}
							{@const isPending = event.type === 'tool_start'}
							{@const toolView = formatToolView(event)}
							<div class="ev {isPending ? 'pending' : (i === 0 ? 'curr' : 'done')}">
								<div class="tm">{formatTime(event.timestamp)}</div>
								{#if toolView}
										<div class="tool-event-card {toolView.phase}">
											<div class="tool-event-head">
												<span class="tool-state">{toolView.phase === 'starting' ? 'Starting' : toolView.phase === 'failed' ? 'Failed' : 'Completed'}</span>
												<span class="tool-name" title={toolView.name}>{toolView.name}</span>
												{#if isPending}<span class="pending-dot">...</span>{/if}
											</div>
										<div class="tool-event-title">{toolView.title}</div>
										{#if toolView.subtitle}
											<div class="tool-event-sub" title={toolView.subtitleTitle || toolView.subtitle}>{toolView.subtitle}</div>
										{/if}
										{#if toolView.rows.length > 0}
											<div class="tool-kv">
												{#each toolView.rows as row}
													<div title={row.title}><span>{row.label}</span><b>{row.value}</b></div>
												{/each}
											</div>
										{/if}
										{#if toolView.items.length > 0}
											<div class="tool-items">
												{#each toolView.items as item}
													<span title={item.title}>{item.label}</span>
												{/each}
											</div>
										{/if}
										{#if toolView.preview}
											<pre class="tool-preview {toolView.previewKind === 'code' ? 'codeish' : ''}" title={toolView.previewTitle || toolView.preview}>{toolView.preview}</pre>
										{/if}
									</div>
								{:else}
									<div class="ti">{event.type}{#if isPending}<span class="pending-dot">...</span>{/if}</div>
								{/if}
								{#if !toolView && stripThinkTags(event.content || '')}
									<div class="body">{stripThinkTags(event.content || '')}</div>
								{/if}
								{#if !toolView && event.data && Object.keys(event.data).length > 0}
									<pre class="code">{truncateJson(event.data)}</pre>
								{/if}
							</div>
						{:else}
							<div class="ev">
								<div class="ti">No events yet</div>
							</div>
						{/each}
					</div>
				{:else if agentDetailTab === 'thinking'}
					{@const thinkingEvents = selectedAgent.events
						.filter(e => (e.type === 'thinking' || e.type === 'reasoning') && stripThinkTags(e.content || '').trim())}
					<div class="timeline">
						{#each thinkingEvents as event, i}
							<div class="ev {i === thinkingEvents.length - 1 ? 'curr' : 'done'}">
								<div class="tm">{formatTime(event.timestamp)}</div>
								<div class="ti">Reasoning</div>
								<div class="body markdown-think">
									<MarkdownContent source={stripThinkTags(event.content || '')} />
								</div>
							</div>
						{:else}
							<div class="ev">
								<div class="ti">No thinking recorded</div>
							</div>
						{/each}
					</div>
				{:else if agentDetailTab === 'tools'}
					<div class="timeline">
						{#each selectedAgent.toolCalls as tool}
							{@const toolView = formatToolView(tool)}
							<div class="ev done">
								<div class="tm">{formatTime(tool.timestamp)}</div>
								{#if toolView}
									<div class="tool-event-card {toolView.phase}">
										<div class="tool-event-head">
											<span class="tool-state">{toolView.phase === 'starting' ? 'Starting' : toolView.phase === 'failed' ? 'Failed' : 'Completed'}</span>
											<span class="tool-name" title={toolView.name}>{toolView.name}</span>
										</div>
										<div class="tool-event-title">{toolView.title}</div>
										{#if toolView.subtitle}
											<div class="tool-event-sub" title={toolView.subtitleTitle || toolView.subtitle}>{toolView.subtitle}</div>
										{/if}
										{#if toolView.rows.length > 0}
											<div class="tool-kv">
												{#each toolView.rows as row}
													<div title={row.title}><span>{row.label}</span><b>{row.value}</b></div>
												{/each}
											</div>
										{/if}
										{#if toolView.items.length > 0}
											<div class="tool-items">
												{#each toolView.items as item}
													<span title={item.title}>{item.label}</span>
												{/each}
											</div>
										{/if}
										{#if toolView.preview}
											<pre class="tool-preview {toolView.previewKind === 'code' ? 'codeish' : ''}" title={toolView.previewTitle || toolView.preview}>{toolView.preview}</pre>
										{/if}
									</div>
								{:else if tool.data && Object.keys(tool.data).length > 0}
									<div class="ti">{tool.data?.tool || tool.type || 'Unknown tool'}</div>
									{@const structured = formatStructuredToolData(tool.data)}
									{#if structured}
										<div class="structured-data">{structured}</div>
									{:else}
										<pre class="code">{truncateJson(tool.data)}</pre>
									{/if}
								{/if}
							</div>
						{:else}
							<div class="ev">
								<div class="ti">No tool calls yet</div>
							</div>
						{/each}
					</div>
				{:else if agentDetailTab === 'tasks'}
					<div class="task-list">
						{#if selectedAgent.tasks.length > 0}
							<div class="task-progress">
								<div class="task-progress-bar" style="width: {selectedAgent.progress?.percent || 0}%"></div>
							</div>
							<div class="task-progress-label">{selectedAgent.progress?.completed || 0} of {selectedAgent.progress?.total || 0} completed</div>
							{#each selectedAgent.tasks as task, i}
								<div class="task-item {task.completed ? 'done' : ''}">
									<span class="task-check">{task.completed ? '✓' : (i + 1)}</span>
									<span class="task-name">{task.name}</span>
								</div>
							{/each}
						{:else}
							<div class="ev">
								<div class="ti">No tasks assigned</div>
							</div>
						{/if}
					</div>
				{/if}

			</div>
				<div class="ap-actions">
					{#if showDirectInput}
						<div class="dir-input">
							<input
								type="text"
								placeholder="Message to {getAgentShortName(selectedAgent.id)}..."
								bind:value={directMessage}
								onkeydown={(e) => { if (e.key === 'Enter' && directMessage.trim()) { handleDirectAgent(selectedAgent.id, directMessage.trim()); directMessage = ''; showDirectInput = false; } if (e.key === 'Escape') { showDirectInput = false; directMessage = ''; } }}
							/>
							<button class="dir-send" onclick={() => { if (directMessage.trim()) { handleDirectAgent(selectedAgent.id, directMessage.trim()); directMessage = ''; showDirectInput = false; } }}>
								<ArrowRight class="h-3.5 w-3.5" />
							</button>
							<button class="dir-cancel" onclick={() => { showDirectInput = false; directMessage = ''; }}>
								<X class="h-3.5 w-3.5" />
							</button>
						</div>
					{:else}
						<button onclick={() => handlePauseAgent(selectedAgent.id)}>
							<Pause class="h-3.5 w-3.5" /> Pause
						</button>
						<button onclick={() => showDirectInput = true}>
							<Zap class="h-3.5 w-3.5" /> Direct
						</button>
						<button class="danger" onclick={() => handlePauseAgent(selectedAgent.id)}>
							<Square class="h-3.5 w-3.5 fill-current" /> Kill
						</button>
						<button onclick={() => handleResumeAgent(selectedAgent.id, 'restart')}>
							<RotateCcw class="h-3.5 w-3.5" /> Restart
						</button>
					{/if}
				</div>
			</aside>
		{/if}
</div>

<style>
	:global(body) { background: var(--paper-1); overflow: hidden; }

	.app { display: flex; height: 100vh; overflow: hidden; }

	.stage { display: flex; flex-direction: column; min-width: 0; background: var(--paper-1); position: relative; flex: 1; }
	.stage::before { content: ""; position: absolute; inset: 0; background: radial-gradient(50% 40% at 12% 0%, oklch(88% 0.08 295 / 0.55), transparent 60%), radial-gradient(40% 30% at 90% 0%, oklch(90% 0.06 220 / 0.45), transparent 65%); pointer-events: none; }

	.topbar { display: flex; align-items: center; gap: 14px; padding: 14px 24px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,0.65); backdrop-filter: blur(18px); position: relative; z-index: 2; }
	.topbar .crumb { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.08em; color: var(--ink-5); min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.topbar .crumb b { color: var(--ink-0); font-weight: 500; }
	.topbar .seg { margin-left: auto; display: inline-flex; padding: 3px; background: var(--paper-1); border: 1px solid var(--line); border-radius: 11px; }
	.topbar .seg button { border: 0; background: transparent; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; color: var(--ink-4); display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
	.topbar .seg button.on { background: var(--paper-0); color: var(--ink-0); box-shadow: 0 1px 4px rgba(20,18,32,0.06), 0 0 0 1px var(--line); }
	.topbar .ico-btn { width: 32px; height: 32px; border-radius: 9px; background: var(--paper-0); border: 1px solid var(--line); display: inline-flex; align-items: center; justify-content: center; color: var(--ink-3); cursor: pointer; }
	.topbar .ico-btn:hover { color: var(--ink-0); border-color: var(--line-strong); }

	.running-pill { display: inline-flex; align-items: center; gap: 7px; padding: 5px 10px 5px 9px; border-radius: 999px; background: oklch(95% 0.04 295); border: 1px solid oklch(85% 0.06 295); color: var(--violet-d); font-size: 11px; font-weight: 500; font-family: var(--font-mono); letter-spacing: 0.06em; }
	.running-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--violet-d); box-shadow: 0 0 8px var(--violet-d); animation: pulse 1.4s ease-in-out infinite; }

	@keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } }
	@keyframes fill { from { width: 8%; } to { width: 92%; } }

	.scroll { flex: 1; overflow-y: auto; padding: 36px 32px 220px; position: relative; z-index: 1; }
	.frame { max-width: 880px; margin: 0 auto; }

	.proj-head { margin-bottom: 32px; }
	.proj-head .eyebrow { color: var(--violet-d); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.08em; }
	.proj-head h1 { font-family: var(--font-display); font-weight: 400; font-size: 56px; line-height: 0.95; letter-spacing: -0.025em; margin: 14px 0 12px; color: var(--ink-0); }
	.proj-head h1 em { font-style: italic; color: var(--violet-d); }
	.proj-head .meta-row { display: flex; gap: 18px; align-items: center; font-family: var(--font-mono); font-size: 11px; color: var(--ink-4); letter-spacing: 0.06em; flex-wrap: wrap; }
	.proj-head .meta-row b { color: var(--ink-1); font-weight: 500; }

	.mesh-card { background: var(--paper-0); border: 1px solid var(--line); border-radius: 24px; padding: 22px; box-shadow: var(--shadow-2); }
	.mesh-card header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; gap: 16px; flex-wrap: wrap; }
	.mesh-card header h3 { margin: 0; font-size: 13.5px; font-weight: 500; letter-spacing: -0.005em; color: var(--ink-0); min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.mesh-card header h3 small { font-family: var(--font-mono); font-size: 11px; color: var(--ink-5); letter-spacing: 0.10em; margin-left: 8px; }
	.mesh-card header .legend { display: flex; gap: 10px; font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.10em; color: var(--ink-5); flex-shrink: 0; flex-wrap: wrap; }
	.mesh-card header .legend span { display: inline-flex; align-items: center; gap: 5px; }
	.mesh-card header .legend i { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }

	.mesh-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }

	.agent { border: 1px solid var(--line); border-radius: 16px; padding: 14px; background: var(--paper-0); cursor: pointer; transition: all 200ms ease; position: relative; overflow: hidden; text-align: left; font-family: inherit; color: inherit; }
	.agent:hover { border-color: var(--line-strong); transform: translateY(-1px); }
	.agent.active { border-color: var(--violet); box-shadow: 0 0 0 4px oklch(70% 0.18 295 / 0.10), 0 8px 24px rgba(124,58,237,0.10); }
	.agent.selected { background: var(--ink-0); color: white; border-color: var(--ink-0); }
	.agent.selected::after { content: ""; position: absolute; inset: 0; background: radial-gradient(60% 80% at 100% 0%, oklch(70% 0.20 295 / 0.30), transparent 60%); pointer-events: none; }
	.agent .row { display: flex; align-items: center; gap: 8px; position: relative; z-index: 1; min-width: 0; }
	.agent .glyph { width: 28px; height: 28px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 11px; font-weight: 600; background: var(--paper-1); color: var(--ink-1); border: 1px solid var(--line); flex-shrink: 0; }
	.agent.selected .glyph { background: rgba(255,255,255,0.10); color: white; border-color: rgba(255,255,255,0.18); }
	.agent .nm { font-size: 13px; font-weight: 500; flex: 1; letter-spacing: -0.005em; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.agent .nm small { font-family: var(--font-mono); font-size: 10px; color: var(--ink-5); letter-spacing: 0.06em; display: block; font-weight: 400; }
	.agent.selected .nm small { color: rgba(255,255,255,0.55); }
	.agent .st { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.10em; padding: 3px 7px; border-radius: 5px; }
	.st.run { background: oklch(96% 0.04 295); color: var(--violet-d); }
	.st.idle { background: var(--paper-1); color: var(--ink-5); }
	.st.queue { background: oklch(96% 0.04 75); color: oklch(50% 0.18 75); }
	.st.review { background: oklch(96% 0.04 220); color: var(--cyan-d); }
	.st.done { background: oklch(95% 0.05 160); color: oklch(48% 0.16 160); }
	.agent.selected .st { background: rgba(255,255,255,0.12); color: white; }
	.agent .bar { margin-top: 12px; position: relative; z-index: 1; height: 3px; background: var(--paper-2); border-radius: 2px; overflow: hidden; }
	.agent.selected .bar { background: rgba(255,255,255,0.10); }
	.agent .bar > div { height: 100%; border-radius: 2px; background: var(--violet); animation: fill 3s ease-in-out infinite alternate; }
	.agent[data-h="cyan"] .bar > div { background: var(--cyan); }
	.agent[data-h="amber"] .bar > div { background: var(--amber); }
	.agent[data-h="green"] .bar > div { background: oklch(72% 0.16 150); }
	.agent[data-h="rose"] .bar > div { background: var(--rose); }
	.agent .meta { margin-top: 9px; position: relative; z-index: 1; display: flex; gap: 12px; font-family: var(--font-mono); font-size: 10px; color: var(--ink-5); letter-spacing: 0.04em; min-width: 0; overflow: hidden; }
	.agent.selected .meta { color: rgba(255,255,255,0.55); }

	.chat { margin-top: 28px; display: flex; flex-direction: column; gap: 14px; }
	.msg { display: flex; gap: 12px; max-width: 720px; min-width: 0; }
	.msg.user { align-self: flex-end; flex-direction: row-reverse; }
	.msg .av-m { width: 30px; height: 30px; border-radius: 9px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 10px; color: var(--ink-5); letter-spacing: 0.04em; background: var(--paper-0); border: 1px solid var(--line); }
	.msg.user .av-m { background: var(--ink-0); color: white; border-color: var(--ink-0); }
	.msg .bub { background: var(--paper-0); border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; font-size: 14.5px; line-height: 1.55; color: var(--ink-1); min-width: 0; overflow-wrap: break-word; word-break: break-word; }
	.msg.user .bub { background: var(--ink-0); color: white; border-color: var(--ink-0); border-top-right-radius: 6px; overflow-wrap: break-word; word-break: break-word; }
	.msg.assistant .bub { border-top-left-radius: 6px; }
	.msg .bub :global(b) { color: var(--violet-d); font-weight: 500; }
	.msg.user .bub :global(b) { color: var(--violet-2); }
	.msg .bub .src { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.10em; color: var(--ink-5); margin-bottom: 6px; }
	.msg .bub :global(code) { font-family: var(--font-mono); font-size: 13px; background: var(--paper-1); padding: 1px 5px; border-radius: 4px; }
	.msg.user .bub :global(code) { background: rgba(255,255,255,0.10); color: white; }
	.msg .bub :global(pre) { margin: 8px 0; padding: 10px 12px; background: var(--paper-1); border: 1px solid var(--line); border-radius: 10px; overflow-x: auto; }
	.msg .bub :global(pre code) { background: transparent; padding: 0; }
	.msg .bub :global(p) { margin: 0; }
	.msg .bub :global(p + p) { margin-top: 0.5em; }
	.msg .bub :global(ul), .msg .bub :global(ol) { margin: 0.4em 0; padding-left: 1.2em; }
	.msg .bub :global(li) { margin: 0.2em 0; }

	.composer-wrap { position: absolute; left: 0; right: 0; bottom: 0; padding: 24px; background: linear-gradient(180deg, transparent, rgba(248,248,250,0.92) 30%, var(--paper-1) 60%); z-index: 5; }
	.composer { max-width: 880px; margin: 0 auto; background: var(--paper-0); border: 1px solid var(--line); border-radius: 22px; padding: 14px; box-shadow: var(--shadow-3); display: flex; flex-direction: column; gap: 10px; }
	.composer:focus-within { border-color: var(--violet); box-shadow: var(--shadow-3), 0 0 0 4px oklch(70% 0.18 295 / 0.10); }
	.composer textarea { border: 0; outline: none; resize: none; font-family: inherit; font-size: 15px; line-height: 1.5; color: var(--ink-0); background: transparent; padding: 6px 4px; min-height: 48px; max-height: 160px; }
	.composer textarea::placeholder { color: var(--ink-5); }
	.composer-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 9px; background: var(--paper-1); border: 1px solid var(--line); font-size: 11.5px; font-family: var(--font-mono); letter-spacing: 0.04em; color: var(--ink-3); cursor: pointer; transition: all 160ms ease; }
	.chip:hover { background: var(--paper-2); }
	.chip.on { background: var(--ink-0); color: white; border-color: var(--ink-0); }
	.chip.on .l { color: var(--violet-2); }
	.composer-foot .send { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px 8px 16px; background: var(--ink-0); color: white; border: 0; border-radius: 11px; font-size: 13px; font-weight: 500; box-shadow: 0 6px 18px rgba(124,58,237,0.20), inset 0 1px 0 rgba(255,255,255,0.10); position: relative; overflow: hidden; cursor: pointer; }
	.composer-foot .send::before { content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, oklch(70% 0.18 295 / 0.20), transparent 60%); }
	.composer-foot .send span, .composer-foot .send kbd, .composer-foot .send :global(svg) { position: relative; z-index: 1; }
	.composer-foot .send:disabled { opacity: 0.5; cursor: not-allowed; }
	.quick { max-width: 880px; margin: 0 auto 10px; display: flex; gap: 8px; flex-wrap: wrap; }
	.quick button { padding: 7px 12px; border-radius: 999px; background: var(--paper-0); border: 1px solid var(--line); font-size: 12.5px; color: var(--ink-2); transition: all 160ms ease; cursor: pointer; font-family: inherit; }
	.quick button:hover { border-color: var(--ink-3); background: white; }
	.quick button span { color: var(--ink-5); margin-right: 5px; font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.06em; }

	.question-wrap { max-width: 880px; margin: 0 auto 16px; padding: 0 32px; }
	.question-panel {
		background: rgba(255,255,255,0.72);
		border: 1px solid rgba(255,255,255,0.68);
		backdrop-filter: blur(22px) saturate(140%);
		-webkit-backdrop-filter: blur(22px) saturate(140%);
		border-radius: 18px;
		box-shadow: var(--shadow-3);
		overflow: hidden;
	}
	.question-head {
		padding: 18px 20px 15px;
		background:
			radial-gradient(80% 120% at 100% 0%, oklch(82% 0.12 295 / 0.26), transparent 62%),
			var(--paper-0);
		border-bottom: 1px solid var(--line);
	}
	.question-kicker {
		display: inline-flex;
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.14em;
		color: var(--violet-d);
		text-transform: uppercase;
	}
	.question-title {
		margin: 7px 0 4px;
		font-family: var(--font-display);
		font-weight: 400;
		font-size: 28px;
		line-height: 1;
		letter-spacing: -0.015em;
		color: var(--ink-0);
	}
	.question-description {
		margin: 0;
		max-width: 62ch;
		color: var(--ink-4);
		font-size: 13px;
		line-height: 1.5;
	}
	.question-list { display: flex; flex-direction: column; gap: 10px; padding: 14px; }
	.question-item {
		border: 1px solid var(--line);
		border-radius: 10px;
		background: var(--paper-0);
		padding: 12px;
	}
	.question-label-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 8px;
	}
	.question-label-row label {
		font-size: 13px;
		font-weight: 600;
		line-height: 1.35;
		color: var(--ink-1);
	}
	.question-label-row span {
		flex-shrink: 0;
		font-family: var(--font-mono);
		font-size: 9px;
		letter-spacing: 0.10em;
		text-transform: uppercase;
		color: var(--ink-5);
		background: var(--paper-1);
		border: 1px solid var(--line);
		border-radius: 5px;
		padding: 2px 6px;
	}
	.question-help {
		margin: -2px 0 9px;
		font-size: 12px;
		color: var(--ink-5);
		line-height: 1.45;
	}
	.question-options {
		display: flex;
		flex-wrap: wrap;
		gap: 7px;
		margin-bottom: 9px;
	}
	.question-options :global(.question-option) {
		border: 1px solid var(--line);
		background: var(--paper-1);
		border-radius: 8px;
		padding: 7px 10px;
		font-size: 12px;
		font-weight: 500;
		color: var(--ink-3);
		transition: all 160ms ease;
	}
	.question-options :global(.question-option:hover) { border-color: var(--line-strong); background: white; }
	.question-options :global(.question-option.selected) {
		background: var(--ink-0);
		border-color: var(--ink-0);
		color: white;
		box-shadow: 0 6px 18px rgba(20,18,32,0.12);
	}
	.question-options.multi :global(.question-option.selected) {
		background: oklch(96% 0.04 295);
		border-color: oklch(70% 0.18 295 / 0.34);
		color: var(--violet-d);
		box-shadow: none;
	}
	.question-input,
	.question-textarea {
		width: 100%;
		border: 1px solid var(--line);
		background: var(--paper-1);
		border-radius: 9px;
		padding: 10px 11px;
		font-family: inherit;
		font-size: 13px;
		line-height: 1.45;
		color: var(--ink-1);
		outline: none;
		transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
	}
	.question-textarea { resize: vertical; min-height: 96px; }
	.question-input:focus,
	.question-textarea:focus {
		background: white;
		border-color: var(--violet);
		box-shadow: 0 0 0 4px oklch(70% 0.18 295 / 0.10);
	}
	.question-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 12px 14px 14px;
		border-top: 1px dashed var(--line);
	}
	.question-count {
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--ink-5);
	}
	.question-submit {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		border: 0;
		border-radius: 10px;
		background: var(--ink-0);
		color: white;
		padding: 9px 13px;
		font-size: 12.5px;
		font-weight: 600;
		box-shadow: 0 8px 22px rgba(20,18,32,0.16);
	}
	.question-submit:disabled { opacity: 0.45; cursor: not-allowed; box-shadow: none; }

	.agent-pane { width: 380px; background: var(--paper-0); border-left: 1px solid var(--line); overflow: hidden; display: flex; flex-direction: column; flex-shrink: 0; }
	.agent-pane .ap-head { padding: 18px 22px 14px; border-bottom: 1px solid var(--line); background: var(--ink-0); color: white; position: relative; overflow: hidden; flex-shrink: 0; }
	.agent-pane .ap-head::before { content:""; position:absolute; inset:0; background: radial-gradient(70% 100% at 100% 0%, oklch(70% 0.20 295 / 0.32), transparent 60%); }
	.agent-pane .ap-head > * { position: relative; z-index: 1; }
	.ap-head .ix { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.14em; color: var(--violet-2); }
	.ap-head h3 { font-family: var(--font-display); font-weight: 400; font-size: 28px; line-height: 1; letter-spacing: -0.02em; margin: 8px 0 4px; color: white; }
	.ap-head h3 em { font-style: italic; color: oklch(78% 0.16 295); }
	.ap-head .role { font-size: 12.5px; color: rgba(255,255,255,0.65); }
	.ap-head .stat-row { margin-top: 14px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.08); display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
	.ap-head .stat-cell .l { font-family: var(--font-mono); font-size: 9.5px; letter-spacing: 0.10em; color: rgba(255,255,255,0.45); }
	.ap-head .stat-cell .v { font-family: var(--font-display); font-size: 22px; line-height: 1.1; letter-spacing: -0.01em; }
	.ap-head .stat-cell .v em { color: oklch(78% 0.16 295); font-style: italic; }

	.ap-tabs { display: flex; padding: 0 22px; border-bottom: 1px solid var(--line); gap: 4px; flex-shrink: 0; }
	.ap-tabs button { border: 0; background: transparent; padding: 12px 0; margin: 0 12px 0 0; font-size: 12.5px; color: var(--ink-4); font-weight: 500; letter-spacing: -0.005em; border-bottom: 2px solid transparent; margin-bottom: -1px; cursor: pointer; }
	.ap-tabs button.on { color: var(--ink-0); border-bottom-color: var(--ink-0); }
	.ap-tabs button .c { font-family: var(--font-mono); font-size: 10px; color: var(--ink-5); margin-left: 4px; }

	.ap-body { padding: 18px 22px; flex: 1; overflow-y: auto; min-height: 0; }
	.timeline { display: flex; flex-direction: column; gap: 10px; }
	.ev { border-left: 1.5px solid var(--line); padding-left: 16px; padding-bottom: 4px; position: relative; }
	.ev::before { content: ""; position: absolute; left: -5px; top: 5px; width: 8px; height: 8px; border-radius: 50%; background: var(--paper-0); border: 1.5px solid var(--ink-3); }
	.ev.curr::before { background: var(--violet); border-color: var(--violet); box-shadow: 0 0 8px var(--violet); }
	.ev.done::before { background: var(--ink-1); border-color: var(--ink-1); }
	.ev .tm { font-family: var(--font-mono); font-size: 10px; color: var(--ink-5); letter-spacing: 0.06em; margin-bottom: 2px; }
	.ev .ti { font-size: 13px; font-weight: 500; color: var(--ink-1); }
	.ev .body { margin-top: 4px; font-size: 12.5px; color: var(--ink-4); line-height: 1.5; }
	.ev .code { margin-top: 6px; font-family: var(--font-mono); font-size: 11px; background: var(--paper-1); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; color: var(--ink-2); white-space: pre-wrap; line-height: 1.5; max-height: 280px; overflow-y: auto; }
	.ev.pending::before { background: var(--violet); border-color: var(--violet); animation: pulse-dot 1.5s ease-in-out infinite; }
	.ev.pending .ti { color: var(--violet); }
	.pending-dot { margin-left: 6px; font-size: 14px; color: var(--violet); animation: pulse-dot 1.5s ease-in-out infinite; display: inline-block; }
	@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
	.tool-event-card {
		margin-top: 6px;
		border: 1px solid var(--line);
		background: var(--paper-0);
		border-radius: 8px;
		padding: 10px 11px;
		box-shadow: 0 4px 14px rgba(20,18,32,0.04);
	}
	.tool-event-card.starting {
		border-color: oklch(70% 0.18 295 / 0.28);
		background: oklch(98% 0.018 295);
	}
	.tool-event-card.failed {
		border-color: oklch(64% 0.18 25 / 0.28);
		background: oklch(98% 0.018 25);
	}
	.tool-event-head {
		display: flex;
		align-items: center;
		gap: 7px;
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--ink-5);
	}
	.tool-state {
		border-radius: 5px;
		background: var(--ink-0);
		color: white;
		padding: 2px 6px;
		font-size: 9px;
		letter-spacing: 0.10em;
	}
	.tool-event-card.starting .tool-state { background: var(--violet-d); }
	.tool-event-card.failed .tool-state { background: var(--rose); }
	.tool-name {
		color: var(--ink-4);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.tool-event-title {
		margin-top: 8px;
		font-size: 13px;
		font-weight: 600;
		letter-spacing: -0.01em;
		color: var(--ink-0);
	}
	.tool-event-sub {
		margin-top: 3px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		line-height: 1.45;
		color: var(--ink-4);
		overflow-wrap: anywhere;
	}
	.tool-kv {
		margin-top: 9px;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
	}
	.tool-kv div {
		min-width: 0;
		border: 1px solid var(--line);
		border-radius: 7px;
		background: var(--paper-1);
		padding: 6px 7px;
	}
	.tool-kv span {
		display: block;
		font-family: var(--font-mono);
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--ink-5);
	}
	.tool-kv b {
		display: block;
		margin-top: 2px;
		font-size: 11px;
		font-weight: 500;
		color: var(--ink-1);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.tool-items {
		margin-top: 9px;
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
	}
	.tool-items span {
		max-width: 100%;
		border: 1px solid var(--line);
		border-radius: 6px;
		background: var(--paper-1);
		padding: 3px 6px;
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--ink-3);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.tool-preview {
		margin: 9px 0 0;
		border: 1px solid var(--line);
		border-radius: 7px;
		background: var(--ink-0);
		color: rgba(255,255,255,0.78);
		padding: 9px 10px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		line-height: 1.55;
		white-space: pre-wrap;
		max-height: 190px;
		overflow: auto;
	}
	.tool-preview.codeish {
		color: oklch(88% 0.03 250);
	}
	.markdown-think { font-size: 12px; line-height: 1.55; }
	.markdown-think :global(p) { margin: 0 0 6px 0; }
	.markdown-think :global(p:last-child) { margin-bottom: 0; }
	.markdown-think :global(ul), .markdown-think :global(ol) { margin: 4px 0; padding-left: 16px; }
	.markdown-think :global(li) { margin: 2px 0; }
	.markdown-think :global(pre) { margin: 6px 0; }
	.structured-data { margin-top: 6px; font-family: var(--font-mono); font-size: 11px; background: var(--paper-1); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; color: var(--ink-2); line-height: 1.6; white-space: pre-wrap; }

	.tool-card { margin-top: 4px; background: var(--paper-1); border: 1px dashed var(--line); border-radius: 12px; padding: 10px 12px; font-family: var(--font-mono); font-size: 11px; color: var(--ink-3); letter-spacing: 0.02em; display: flex; flex-direction: column; gap: 8px; }
	.tool-card .tool-head { display: flex; align-items: center; gap: 10px; }
	.tool-card .tag { color: var(--violet-d); font-weight: 600; background: oklch(96% 0.04 295); padding: 2px 6px; border-radius: 4px; flex-shrink: 0; }
	.tool-card .tool-summary { color: var(--ink-4); }
	.tool-details { display: flex; flex-direction: column; gap: 4px; padding-top: 6px; border-top: 1px dashed var(--line); }
	.tool-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
	.td-check { width: 16px; height: 16px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; flex-shrink: 0; color: var(--ink-5); }
	.td-check.done { color: var(--violet); font-weight: 700; }
	.td-label { font-size: 11px; color: var(--ink-2); line-height: 1.4; }
	.td-label.done { text-decoration: line-through; color: var(--ink-5); }
	.td-meta { margin-left: auto; font-size: 10px; color: var(--ink-5); flex-shrink: 0; }
	.tool-meta { font-size: 10px; color: var(--ink-5); margin-top: 2px; }

	.task-list { display: flex; flex-direction: column; gap: 2px; }
	.task-progress { height: 3px; background: var(--line); border-radius: 2px; overflow: hidden; margin-bottom: 10px; }
	.task-progress-bar { height: 100%; background: var(--violet); border-radius: 2px; transition: width 300ms ease; }
	.task-progress-label { font-family: var(--font-mono); font-size: 10px; color: var(--ink-5); letter-spacing: 0.06em; margin-bottom: 12px; }
	.task-item { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 8px; transition: background 120ms ease; }
	.task-item:hover { background: var(--paper-1); }
	.task-check { width: 20px; height: 20px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 10px; font-weight: 600; background: var(--paper-0); border: 1px solid var(--line); color: var(--ink-3); flex-shrink: 0; }
	.task-item.done .task-check { background: var(--violet); border-color: var(--violet); color: white; }
	.task-name { font-size: 12.5px; color: var(--ink-1); line-height: 1.4; }
	.task-item.done .task-name { text-decoration: line-through; color: var(--ink-4); }

	.ap-actions { padding: 14px 22px; border-top: 1px dashed var(--line); display: grid; grid-template-columns: 1fr 1fr; gap: 6px; flex-shrink: 0; }
	.ap-actions button { border: 1px solid var(--line); background: var(--paper-0); border-radius: 10px; padding: 9px 12px; font-size: 12px; font-weight: 500; color: var(--ink-2); display: inline-flex; align-items: center; gap: 7px; transition: all 160ms ease; cursor: pointer; }
	.ap-actions button:hover { background: var(--paper-1); border-color: var(--line-strong); }
	.ap-actions button.danger { color: var(--rose); }

	.dir-input { display: flex; align-items: center; gap: 6px; grid-column: 1 / -1; }
	.dir-input input { flex: 1; min-width: 0; background: var(--paper-1); border: 1px solid var(--line); border-radius: 10px; padding: 9px 12px; font-size: 12px; color: var(--ink-1); outline: none; transition: border-color 160ms ease; }
	.dir-input input:focus { border-color: var(--violet); }
	.dir-input input::placeholder { color: var(--ink-5); }
	.dir-send { border: 0; background: var(--violet); color: white; border-radius: 10px; padding: 9px 11px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: opacity 160ms ease; flex-shrink: 0; }
	.dir-send:hover { opacity: 0.85; }
	.dir-cancel { border: 1px solid var(--line); background: var(--paper-0); color: var(--ink-3); border-radius: 10px; padding: 9px 11px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: all 160ms ease; flex-shrink: 0; }
	.dir-cancel:hover { background: var(--paper-1); border-color: var(--line-strong); color: var(--ink-1); }

	.code-pane { width: min(860px, 58vw); }
	@media (max-width: 1280px){ .agent-pane { width: 340px; } .code-pane { width: min(720px, 55vw); } }
	@media (max-width: 1080px){ :global(.side) { width: 60px !important; padding: 18px 8px !important; } :global(.side .side-scroll) { display: none !important; } :global(.side .me) { display: flex !important; padding: 8px !important; justify-content: center !important; } :global(.side .me .av) { margin: 0 !important; } :global(.side .me .info), :global(.side .me a) { display: none !important; } .agent-pane { display:none; } .mesh-grid { grid-template-columns: repeat(2, 1fr); } .proj-head h1 { font-size: 42px; } }
	@media (max-width: 1080px){ :global(.side) { width: 60px !important; padding: 18px 8px !important; } :global(.side .side-scroll) { display: none !important; } :global(.side .me) { display: flex !important; padding: 8px !important; justify-content: center !important; } :global(.side .me .av) { margin: 0 !important; } :global(.side .me .info), :global(.side .me a) { display: none !important; } .agent-pane { display:none; } .mesh-grid { grid-template-columns: repeat(2, 1fr); } .proj-head h1 { font-size: 42px; } }
	@media (max-width: 768px){ .app { flex-direction: column; } .side { width: 100%; height: auto; border-right: none; border-bottom: 1px solid var(--line); } .stage { min-height: 50vh; } .agent-pane { display:none; } }
</style>
