<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { ScrollArea } from "$lib/components/ui/scroll-area";
	import { ChatMessage } from "$lib/components/chat";
	import {
		MeshGrid,
		AgentDetail,
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
	import Play from '@lucide/svelte/icons/play';
	import Eye from '@lucide/svelte/icons/eye';
	import Code2 from '@lucide/svelte/icons/code-2';
	import Settings from '@lucide/svelte/icons/settings';
	import Square from '@lucide/svelte/icons/square';
	import { settings } from "$lib/settings.svelte";

	let inputValue = $state("");
	let aguiClient: AGUIClient | null = null;
	let activeProjectId = $state<string | null>(null);
	let pendingQuestion = $state<{ question_id: string; questions: string[] } | null>(null);
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

	let chatHistory = $state<
		{ role: "user" | "assistant"; content: string; metadata?: any }[]
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
		isSubmittingAnswers = true;
		try {
			await fetch(`/api/projects/${activeProjectId}/answer`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					question_id: pendingQuestion.question_id,
					answers: questionAnswers,
				}),
			});
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
				const data = event.data as { question_id: string; questions: string[] } | undefined;
				if (data?.question_id && Array.isArray(data.questions)) {
					pendingQuestion = { question_id: data.question_id, questions: data.questions };
					questionAnswers = new Array(data.questions.length).fill('');
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
</script>

<div class="flex h-screen w-full siri-mesh-bg text-foreground overflow-hidden">
	<!-- Left: Project Sidebar -->
	<ProjectSidebar
		{activeProjectId}
		isCollapsed={isSidebarCollapsed}
		{isMobile}
		onToggle={() => (isSidebarCollapsed = !isSidebarCollapsed)}
		onSelect={switchProject}
		onNew={startNewProject}
		onDelete={deleteProject}
	/>

	<!-- Right: Main Content -->
	<div class="flex flex-1 flex-col overflow-hidden relative">
		<!-- Header -->
		<header
			class="mx-4 mt-4 rounded-[2rem] flex items-center gap-3 border border-white/50 bg-white/40 shadow-[0_8px_30px_rgb(0,0,0,0.04)] backdrop-blur-xl px-6 py-4 shrink-0 transition-all"
		>
			{#if isMobile && isSidebarCollapsed}
				<button
					onclick={() => (isSidebarCollapsed = false)}
					class="h-9 w-9 flex items-center justify-center rounded-xl border border-white/40 bg-white/40 shadow-sm text-muted-foreground hover:bg-white transition-all mr-1"
				>
					<PanelLeftOpen class="h-4.5 w-4.5" />
				</button>
			{/if}

			<div
				class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/20 shadow-[0_0_12px_rgba(var(--primary),0.1)]"
			>
				<Hexagon class="h-4.5 w-4.5 text-primary" />
			</div>
			<div class="flex flex-col">
				<h1 class="text-sm font-bold tracking-tight">Chorus</h1>
				<span
					class="text-[10px] text-muted-foreground/60 uppercase tracking-[0.12em] font-medium"
					>Parallel Mesh Architecture</span
				>
			</div>
			<div class="ml-auto flex items-center gap-4">
				<div
					class="flex items-center rounded-full border border-white/45 bg-white/30 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_10px_28px_rgba(15,23,42,0.12)] backdrop-blur-3xl"
				>
					<button
						type="button"
						class="relative overflow-hidden flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-medium transition-all duration-200 {!isPlanMode
							? 'text-slate-900 shadow-[0_10px_24px_rgba(15,23,42,0.14)] ring-1 ring-white/65'
							: 'text-muted-foreground hover:bg-white/35 hover:text-foreground'}"
						onclick={() => setPlanMode(false)}
					>
						{#if !isPlanMode}
							<span
								class="pointer-events-none absolute inset-[1px] rounded-full bg-[linear-gradient(180deg,rgba(255,255,255,0.58),rgba(255,255,255,0.22)_54%,rgba(255,255,255,0.1))] backdrop-blur-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.96),inset_0_-1px_0_rgba(255,255,255,0.18),0_14px_28px_rgba(15,23,42,0.12)]"
							></span>
							<span
								class="pointer-events-none absolute inset-x-2 top-1 h-px rounded-full bg-white/85 blur-[1px]"
							></span>
							<span
								class="pointer-events-none absolute inset-x-2 bottom-1 h-2 rounded-full bg-primary/10 blur-md"
							></span>
						{/if}
						<Hexagon class="relative z-10 h-3.5 w-3.5" />
						<span class="relative z-10 hidden sm:inline">Build</span
						>
					</button>
					<button
						type="button"
						class="relative overflow-hidden flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-medium transition-all duration-200 {isPlanMode
							? 'text-slate-900 shadow-[0_10px_24px_rgba(15,23,42,0.14)] ring-1 ring-white/65'
							: 'text-muted-foreground hover:bg-white/35 hover:text-foreground'}"
						onclick={() => setPlanMode(true)}
					>
						{#if isPlanMode}
							<span
								class="pointer-events-none absolute inset-[1px] rounded-full bg-[linear-gradient(180deg,rgba(255,255,255,0.62),rgba(255,255,255,0.26)_54%,rgba(255,255,255,0.12))] backdrop-blur-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.96),inset_0_-1px_0_rgba(255,255,255,0.22),0_14px_28px_rgba(15,23,42,0.14)]"
							></span>
							<span
								class="pointer-events-none absolute inset-x-2 top-1 h-px rounded-full bg-white/85 blur-[1px]"
							></span>
							<span
								class="pointer-events-none absolute inset-x-2 bottom-1 h-2 rounded-full bg-primary/10 blur-md"
							></span>
						{/if}
						<Map class="relative z-10 h-3.5 w-3.5" />
						<span class="relative z-10 hidden sm:inline">Plan</span>
					</button>
				</div>
				{#if activeProjectId}
					<div
						class="flex items-center rounded-full border border-white/45 bg-white/30 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_10px_28px_rgba(15,23,42,0.12)] backdrop-blur-3xl"
					>
						<button
							type="button"
							class="relative overflow-hidden flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-medium transition-all duration-200 {showVersionHistory
								? 'text-slate-900 shadow-[0_10px_24px_rgba(15,23,42,0.14)] ring-1 ring-white/65'
								: 'text-muted-foreground hover:bg-white/35 hover:text-foreground'}"
							onclick={toggleVersionHistory}
						>
							{#if showVersionHistory}
								<span
									class="pointer-events-none absolute inset-[1px] rounded-full bg-[linear-gradient(180deg,rgba(255,255,255,0.62),rgba(255,255,255,0.26)_54%,rgba(255,255,255,0.12))] backdrop-blur-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.96),inset_0_-1px_0_rgba(255,255,255,0.22),0_14px_28px_rgba(15,23,42,0.14)]"
								></span>
								<span
									class="pointer-events-none absolute inset-x-2 top-1 h-px rounded-full bg-white/85 blur-[1px]"
								></span>
								<span
									class="pointer-events-none absolute inset-x-2 bottom-1 h-2 rounded-full bg-primary/10 blur-md"
								></span>
							{/if}
							<History class="relative z-10 h-3.5 w-3.5" />
							<span class="relative z-10 hidden sm:inline"
								>History</span
							>
						</button>
						<button
							type="button"
							class="relative overflow-hidden flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-medium transition-all duration-200 {isCodeViewCollapsed
								? 'text-muted-foreground hover:bg-white/35 hover:text-foreground'
								: 'text-slate-900 shadow-[0_10px_24px_rgba(15,23,42,0.14)] ring-1 ring-white/65'}"
							onclick={toggleCodeView}
						>
							{#if !isCodeViewCollapsed}
								<span
									class="pointer-events-none absolute inset-[1px] rounded-full bg-[linear-gradient(180deg,rgba(255,255,255,0.62),rgba(255,255,255,0.26)_54%,rgba(255,255,255,0.12))] backdrop-blur-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.96),inset_0_-1px_0_rgba(255,255,255,0.22),0_14px_28px_rgba(15,23,42,0.14)]"
								></span>
								<span
									class="pointer-events-none absolute inset-x-2 top-1 h-px rounded-full bg-white/85 blur-[1px]"
								></span>
								<span
									class="pointer-events-none absolute inset-x-2 bottom-1 h-2 rounded-full bg-primary/10 blur-md"
								></span>
							{/if}
							<Code2 class="relative z-10 h-3.5 w-3.5" />
							<span class="relative z-10 hidden sm:inline"
								>Code</span
							>
						</button>
					</div>
				{/if}
				{#if isRunning}
					<button
						type="button"
						onclick={handleStopSwarm}
						class="flex items-center gap-1.5 rounded-full bg-rose-500/10 border border-rose-500/20 px-3 py-1 text-[11px] font-medium text-rose-600 hover:bg-rose-500/20 transition-colors cursor-pointer"
						title="Stop all running agents"
					>
						<Square class="h-3 w-3 fill-current" />
						<span>Stop</span>
					</button>
					<div
						class="flex items-center gap-2 rounded-full bg-primary/10 border border-primary/20 px-3 py-1"
					>
						<span class="relative flex h-2 w-2">
							<span
								class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60"
							></span>
							<span
								class="relative inline-flex h-2 w-2 rounded-full bg-primary"
							></span>
						</span>
						<span class="text-[11px] font-medium text-primary"
							>{agentRegistry.activeAgents.length} active</span
						>
					</div>
				{/if}
				<span
					class="text-[11px] text-muted-foreground/50 hidden sm:inline"
				>
					Powered by MiniMax M2.7
				</span>
			</div>
		</header>

		<!-- Main content areas -->
		<div class="flex flex-1 overflow-hidden">
			<!-- Left: Mesh Grid -->
			<main class="flex flex-1 flex-col overflow-hidden">
				<ScrollArea class="flex-1 min-h-0">
					<div class="p-5 space-y-5 max-w-6xl mx-auto">
						<!-- Chat Transcript -->
						{#if chatHistory.length > 0}
							<div class="space-y-4">
								{#each chatHistory as message, index (index)}
									<ChatMessage
										message={{
											id: `${index}`,
											role: message.role,
											content: message.content,
											timestamp: Date.now(),
										}}
									/>
								{/each}
							</div>
						{/if}

						<!-- Plan Mode: Live Activity -->
						{#if isPlanMode &&
							(hasPlanTelemetry ||
								isExecutingPlan ||
								Boolean(planResponse) ||
								Boolean(specContent))}
							<PlanActivityPanel
								agents={planAgents}
								isStreaming={isExecutingPlan || isRunning}
								hasSpec={Boolean(specContent)}
								statusLabel={planActivityStatusLabel}
							/>
						{/if}

						<!-- Plan Mode: SPEC.md Viewer/Editor -->
						{#if specContent}
							<div
								class="rounded-[2.5rem] border border-cyan-200/45 bg-[linear-gradient(145deg,rgba(255,255,255,0.88),rgba(239,246,255,0.68))] p-4 shadow-[0_24px_70px_rgba(15,23,42,0.12)] backdrop-blur-2xl"
							>
								<div
									class="flex flex-wrap items-start justify-between gap-4 border-b border-white/55 pb-4"
								>
									<div class="max-w-3xl">
										<div class="flex items-center gap-3">
											<div
												class="flex h-11 w-11 items-center justify-center rounded-2xl border border-cyan-200/60 bg-cyan-50/80 text-cyan-700 shadow-[0_0_20px_rgba(34,211,238,0.18)]"
											>
												<Map class="h-5 w-5" />
											</div>
											<div>
												<p
													class="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-700/70"
												>
													Plan Mode
												</p>
												<h3
													class="text-xl font-semibold tracking-tight text-slate-900"
												>
													SPEC.md implementation
													review
												</h3>
											</div>
										</div>
										<p
											class="mt-3 max-w-2xl text-sm leading-6 text-slate-600"
										>
											This is the review surface for the
											generated specification. Rendered
											Markdown, Mermaid diagrams, and the
											approval action are all designed to
											feel closer to a professional IDE
											planning stage.
										</p>
									</div>
									<div class="flex flex-wrap gap-2">
										<div
											class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm"
										>
											{planMetrics.lines} lines
										</div>
										<div
											class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm"
										>
											{planMetrics.words} words
										</div>
										<div
											class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm"
										>
											{planMetrics.headings} headings
										</div>
										<div
											class="rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-[11px] font-medium text-slate-600 shadow-sm"
										>
											{planMetrics.mermaidBlocks} diagrams
										</div>
									</div>
								</div>

								<div
									class="mt-4 grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]"
								>
									<div class="space-y-4">
										<div
											class="rounded-[2rem] border border-white/60 bg-white/60 p-4 shadow-[0_12px_28px_rgba(15,23,42,0.06)]"
										>
											<p
												class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500"
											>
												Plan Snapshot
											</p>
											<div
												class="mt-4 grid grid-cols-2 gap-3"
											>
												<div
													class="rounded-2xl border border-white/70 bg-white/80 p-3"
												>
													<p
														class="text-[11px] text-slate-500"
													>
														Sections
													</p>
													<p
														class="mt-1 text-lg font-semibold text-slate-900"
													>
														{planMetrics.headings}
													</p>
												</div>
												<div
													class="rounded-2xl border border-white/70 bg-white/80 p-3"
												>
													<p
														class="text-[11px] text-slate-500"
													>
														Lists
													</p>
													<p
														class="mt-1 text-lg font-semibold text-slate-900"
													>
														{planMetrics.listItems}
													</p>
												</div>
												<div
													class="rounded-2xl border border-white/70 bg-white/80 p-3"
												>
													<p
														class="text-[11px] text-slate-500"
													>
														Code
													</p>
													<p
														class="mt-1 text-lg font-semibold text-slate-900"
													>
														{planMetrics.codeBlocks}
													</p>
												</div>
												<div
													class="rounded-2xl border border-white/70 bg-white/80 p-3"
												>
													<p
														class="text-[11px] text-slate-500"
													>
														Mermaid
													</p>
													<p
														class="mt-1 text-lg font-semibold text-slate-900"
													>
														{planMetrics.mermaidBlocks}
													</p>
												</div>
											</div>
										</div>

										<div
											class="rounded-[2rem] border border-white/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.82),rgba(245,250,255,0.72))] p-4 shadow-[0_12px_28px_rgba(15,23,42,0.06)]"
										>
											<p
												class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500"
											>
												Workflow
											</p>
											<div class="mt-3 space-y-3">
												<div
													class="flex items-start gap-3"
												>
													<div
														class="mt-1 h-2.5 w-2.5 rounded-full bg-cyan-500 shadow-[0_0_12px_rgba(34,211,238,0.45)]"
													></div>
													<div>
														<p
															class="text-sm font-medium text-slate-900"
														>
															Review plan
														</p>
														<p
															class="text-[12px] leading-5 text-slate-500"
														>
															Inspect the
															generated Markdown
															and diagrams.
														</p>
													</div>
												</div>
												<div
													class="flex items-start gap-3"
												>
													<div
														class="mt-1 h-2.5 w-2.5 rounded-full bg-amber-500 shadow-[0_0_12px_rgba(245,158,11,0.35)]"
													></div>
													<div>
														<p
															class="text-sm font-medium text-slate-900"
														>
															Edit if needed
														</p>
														<p
															class="text-[12px] leading-5 text-slate-500"
														>
															Make changes before
															approval, then keep
															the rendered preview
															in sync.
														</p>
													</div>
												</div>
												<div
													class="flex items-start gap-3"
												>
													<div
														class="mt-1 h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.35)]"
													></div>
													<div>
														<p
															class="text-sm font-medium text-slate-900"
														>
															Approve & execute
														</p>
														<p
															class="text-[12px] leading-5 text-slate-500"
														>
															The approved SPEC is
															written back and the
															build swarm starts.
														</p>
													</div>
												</div>
											</div>
										</div>

										<div
											class="rounded-[2rem] border border-white/60 bg-white/60 p-4 shadow-[0_12px_28px_rgba(15,23,42,0.06)]"
										>
											<p
												class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500"
											>
												Status
											</p>
											<p
												class="mt-3 text-sm leading-6 text-slate-600"
											>
												{#if isEditingSpec}
													You are editing the plan.
													Save to keep your changes,
													or cancel to restore the
													last approved text.
												{:else}
													The generated plan is ready
													for inspection. Use the
													review pane to validate the
													scope before execution.
												{/if}
											</p>
										</div>
									</div>

									<div
										class="overflow-hidden rounded-[2.25rem] border border-white/65 bg-white/75 shadow-[0_16px_40px_rgba(15,23,42,0.08)]"
									>
										<div
											class="flex flex-wrap items-center justify-between gap-3 border-b border-white/60 px-4 py-3"
										>
											<div
												class="flex items-center gap-2"
											>
												<div
													class="rounded-full border border-cyan-200/60 bg-cyan-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-700"
												>
													{isEditingSpec
														? "Editing"
														: "Preview"}
												</div>
												<span
													class="text-[12px] text-slate-500"
													>Markdown + Mermaid renderer</span
												>
											</div>
											<div class="flex gap-2">
												{#if isEditingSpec}
													<Button
														variant="outline"
														size="sm"
														onclick={handleCancelEditSpec}
													>
														Cancel
													</Button>
													<Button
														size="sm"
														onclick={handleSaveSpec}
													>
														Save Changes
													</Button>
												{:else}
													<Button
														variant="outline"
														size="sm"
														onclick={handleEditSpec}
													>
														Edit Plan
													</Button>
												{/if}
											</div>
										</div>

										{#if isEditingSpec}
											<div
												class="grid gap-0 xl:grid-cols-2"
											>
												<div
													class="border-b border-white/50 xl:border-b-0 xl:border-r xl:border-white/50"
												>
													<div class="p-4">
														<div
															class="mb-2 block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500"
														>
															SPEC editor
														</div>
														<textarea
															bind:value={
																editedSpecContent
															}
															class="h-[560px] w-full resize-none rounded-3xl border border-cyan-200/40 bg-slate-950/96 p-4 font-mono text-[13px] leading-6 text-slate-100 shadow-[0_16px_36px_rgba(15,23,42,0.22)] outline-none placeholder:text-slate-500 focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-200/40"
															placeholder="Edit SPEC.md content..."
														></textarea>
													</div>
												</div>
												<div class="min-w-0 p-4">
													<div
														class="mb-2 flex items-center justify-between"
													>
														<div
															class="block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500"
														>
															Live preview
														</div>
														{#if editedSpecContent !== specContent}
															<span
																class="rounded-full border border-amber-200/60 bg-amber-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-700"
															>
																Unsaved changes
															</span>
														{/if}
													</div>
													<div
														class="h-[560px] overflow-y-auto rounded-3xl border border-white/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.86),rgba(247,250,252,0.78))] p-5"
													>
														<PlanSpecPreview
															source={editedSpecContent}
														/>
													</div>
												</div>
											</div>
										{:else}
											<div
												class="h-[620px] overflow-y-auto p-5"
											>
												<PlanSpecPreview
													source={editedSpecContent}
												/>
											</div>
										{/if}

										<div
											class="border-t border-white/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.72),rgba(247,250,252,0.92))] px-4 py-4"
										>
											<div
												class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between"
											>
												<p
													class="text-sm leading-6 text-slate-600"
												>
													Review the generated plan
													carefully. If it looks
													right, approve it and start
													the implementation swarm.
												</p>
												<div
													class="flex flex-wrap gap-3"
												>
													<Button
														variant="outline"
														onclick={() => {
															specContent = null;
															editedSpecContent =
																"";
															planResponse = null;
															isEditingSpec = false;
														}}
													>
														Discard
													</Button>
													<Button
														onclick={handleExecutePlan}
														disabled={isExecutingPlan ||
															isRunning}
													>
														{#if isExecutingPlan}
															<Loader2
																class="h-4 w-4 animate-spin mr-2"
															/>
														{:else}
															<Play
																class="h-4 w-4 mr-2"
															/>
														{/if}
														Approve & Execute
													</Button>
												</div>
											</div>
										</div>
									</div>
								</div>
							</div>
						{/if}

						<!-- Agent Mesh Grid -->
						{#if !isPlanMode}
							<MeshGrid
								agents={allAgents}
								selectedId={agentRegistry.selectedAgentId}
								onSelect={(id) => agentRegistry.selectAgent(id)}
								projectId={activeProjectId}
								onPause={handlePauseAgent}
								onResume={handleResumeAgent}
								onDirect={handleDirectAgent}
							/>
						{/if}

						<!-- Download -->
						{#if downloadReady && downloadData}
							<DownloadButtons
								projectName={downloadData.project_name}
								projectId={downloadData.project_id}
								zipUrl={downloadData.zip_url}
								downloadUrl={downloadData.download_url}
							/>
						{/if}
					</div>
				</ScrollArea>

				<!-- Question Card — shown when an agent calls ask_user() -->
				{#if pendingQuestion}
					<div class="mx-4 mb-3 shrink-0 flex justify-center">
						<div class="w-full max-w-3xl rounded-2xl border border-white/50 bg-white/40 backdrop-blur-xl shadow-lg p-5">
							<p class="text-sm font-semibold text-foreground mb-3">
								The agent needs a few answers to continue:
							</p>
							<div class="flex flex-col gap-3">
								{#each pendingQuestion.questions as question, i}
									<div class="flex flex-col gap-1">
										<label class="text-sm text-muted-foreground" for={`agent-question-${i}`}>{question}</label>
										<Input
											id={`agent-question-${i}`}
											value={questionAnswers[i]}
											oninput={(e) => { questionAnswers[i] = e.currentTarget.value; }}
											placeholder="Your answer…"
											class="h-10 border border-white/60 bg-white/60 backdrop-blur-sm rounded-xl px-3 text-sm focus-visible:ring-1 focus-visible:ring-primary/40"
										/>
									</div>
								{/each}
							</div>
							<div class="mt-4 flex justify-end">
								<Button
									onclick={submitAnswers}
									disabled={isSubmittingAnswers || questionAnswers.some((a) => !a.trim())}
									class="rounded-xl px-5 h-9 text-sm"
								>
									{#if isSubmittingAnswers}
										<Loader2 class="h-4 w-4 animate-spin mr-2" />
									{/if}
									Submit Answers
								</Button>
							</div>
						</div>
					</div>
				{/if}

				<!-- Input Area -->
				<div class="mt-4 mb-8 px-4 shrink-0 flex justify-center">
					<form
						class="flex w-full max-w-3xl items-center gap-2 rounded-[2.5rem] border {isPlanMode
							? 'border-primary/40 bg-primary/5'
							: 'border-white/60 bg-white/60'} shadow-[0_8px_30px_rgb(0,0,0,0.06)] backdrop-blur-xl p-2.5 transition-all {isPlanMode
							? 'focus-within:bg-primary/10'
							: 'focus-within:bg-white/80'} focus-within:shadow-[0_8px_40px_rgb(0,0,0,0.1)]"
						onsubmit={(e: SubmitEvent) => {
							e.preventDefault();
							handleSubmit();
						}}
					>
						<div class="relative flex-1 flex items-center">
							<Input
								bind:value={inputValue}
								placeholder={activeProjectId
									? "Ask for a modification... (e.g., Add Stripe billing and an admin dashboard)"
									: "Describe your project... (e.g., Build a task manager with Spring Boot and Svelte)"}
								disabled={isRunning}
								class="h-12 w-full border-0 bg-transparent px-5 text-[15px] shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50 text-foreground"
							/>
							{#if inputValue}
								<button
									type="button"
									class="absolute right-3 text-muted-foreground/40 hover:text-muted-foreground transition-colors p-1"
									onclick={() => (inputValue = "")}
								>
									<span class="text-lg leading-none"
										>&times;</span
									>
								</button>
							{/if}
						</div>
						<Button
							type="submit"
							disabled={isRunning || !inputValue.trim()}
							class="h-12 w-12 rounded-full p-0 shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground shadow-[0_0_15px_rgba(var(--primary),0.3)] transition-all duration-300 hover:scale-105 disabled:opacity-50 disabled:hover:scale-100"
						>
							{#if isRunning}
								<Loader2 class="h-5 w-5 animate-spin" />
							{:else if isPlanMode}
								<Map class="h-5 w-5 ml-0.5" />
							{:else}
								<Send class="h-5 w-5 ml-0.5" />
							{/if}
						</Button>
				</form>
					{#if planResponse && !specContent && !isPlanMode}
						<div
							class="mt-3 flex items-center gap-2 rounded-full bg-primary/10 border border-primary/30 px-4 py-2 text-[12px] font-medium text-primary"
						>
							<Loader2 class="h-4 w-4 animate-spin" />
							{planResponse}
						</div>
					{/if}
				</div>
			</main>

			<!-- Right: Agent Detail Panel -->
		{#if selectedAgent && !isPlanMode}
			<aside class="w-[470px] shrink-0 animate-fade-in">
				<AgentDetail
					agent={selectedAgent}
					onClose={() => agentRegistry.selectAgent(null)}
				/>
				</aside>
			{/if}

			<!-- Version History Panel -->
			{#if showVersionHistory && activeProjectId}
				<aside
					class="h-full min-h-0 w-[520px] shrink-0 animate-fade-in px-4 py-4"
				>
					<VersionHistory
						projectId={activeProjectId}
						onClose={() => (showVersionHistory = false)}
						onRestore={handleVersionRestore}
					/>
				</aside>
			{/if}

			<!-- Code View Panel -->
			{#if !isCodeViewCollapsed && activeProjectId}
				<aside
					class="w-[920px] max-w-[calc(100vw-2rem)] shrink-0 animate-fade-in px-4 py-4"
				>
					<CodeView
						files={workspaceFiles}
						projectId={activeProjectId}
						collapsed={isCodeViewCollapsed}
						onToggleCollapse={toggleCodeView}
						{lastWrittenFile}
					/>
				</aside>
			{/if}
		</div>
	</div>
</div>
