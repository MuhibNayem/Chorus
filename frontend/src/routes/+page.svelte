<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import { MeshGrid, AgentDetail, GlobalProgress } from '$lib/components/mesh';
	import { DownloadButtons } from '$lib/components/chat';
	import { agentRegistry } from '$lib/agent-registry.svelte';
	import { AGUIClient } from '$lib/aguiclient';
	import { Send, Sparkles, Loader2, Hexagon, AlertTriangle } from 'lucide-svelte';

	let inputValue = $state('');
	let aguiClient: AGUIClient | null = null;

	let chatHistory = $state<{ role: 'user' | 'assistant'; content: string }[]>([]);

	const selectedAgent = $derived(agentRegistry.selectedAgent);
	const allAgents = $derived(agentRegistry.allAgents);
	const isRunning = $derived(agentRegistry.isRunning);
	const globalProgress = $derived(agentRegistry.globalProgress);
	const downloadReady = $derived(agentRegistry.downloadReady);
	const downloadData = $derived(agentRegistry.downloadData);
	const hasError = $derived(agentRegistry.hasError);
	const errorMessage = $derived(agentRegistry.errorMessage);

	async function handleSubmit() {
		const message = inputValue.trim();
		if (!message || isRunning) return;

		inputValue = '';
		chatHistory = [...chatHistory, { role: 'user', content: message }];
		agentRegistry.reset();
		agentRegistry.isRunning = true;

		try {
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ message })
			});

			if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			}

			const data = await res.json();
			const projectId = data.project_id;

			if (!projectId) {
				throw new Error('No project_id returned');
			}

			connectStream(projectId, message);
		} catch (err: any) {
			agentRegistry.isRunning = false;
			chatHistory = [...chatHistory, { role: 'assistant', content: `Error: ${err.message}` }];
		}
	}

	function connectStream(projectId: string, _message: string) {
		if (aguiClient) {
			aguiClient.disconnect();
		}

		aguiClient = new AGUIClient({
			onRawEvent: (event) => {
				agentRegistry.dispatchEvent(event);
			},
			onText: (event) => {
				if (event.content) {
					chatHistory = [...chatHistory, {
						role: 'assistant',
						content: `[${event.agent_name || 'Agent'}]: ${event.content}`
					}];
				}
			},
			onError: (event) => {
				console.error('SSE error event:', event);
			}
		});

		aguiClient.connect(projectId, _message);
	}

	onMount(() => {
		agentRegistry.initialize();
		chatHistory = [
			{
				role: 'assistant',
				content: 'Welcome! I can generate full Spring Boot + Svelte projects from your description. What would you like to build?'
			}
		];
	});

	onDestroy(() => {
		if (aguiClient) {
			aguiClient.disconnect();
		}
	});
</script>

<div class="flex h-screen flex-col siri-mesh-bg text-foreground">
	<!-- Header -->
	<header class="mx-4 mt-4 rounded-[2rem] flex items-center gap-3 border border-white/50 bg-white/40 shadow-[0_8px_30px_rgb(0,0,0,0.04)] backdrop-blur-xl px-6 py-4 shrink-0 transition-all">
		<div class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/20 shadow-[0_0_12px_rgba(var(--primary),0.1)]">
			<Hexagon class="h-4.5 w-4.5 text-primary" />
		</div>
		<div class="flex flex-col">
			<h1 class="text-sm font-bold tracking-tight">Chorus Agent Swarm</h1>
			<span class="text-[10px] text-muted-foreground/60 uppercase tracking-[0.12em] font-medium">Parallel Mesh Architecture</span>
		</div>
		<div class="ml-auto flex items-center gap-4">
			{#if isRunning}
				<div class="flex items-center gap-2 rounded-full bg-primary/10 border border-primary/20 px-3 py-1">
					<span class="relative flex h-2 w-2">
						<span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60"></span>
						<span class="relative inline-flex h-2 w-2 rounded-full bg-primary"></span>
					</span>
					<span class="text-[11px] font-medium text-primary">{agentRegistry.activeAgents.length} active</span>
				</div>
			{/if}
			<span class="text-[11px] text-muted-foreground/50 hidden sm:inline">
				Powered by MiniMax M2.7
			</span>
		</div>
	</header>

	<!-- Main Content -->
	<div class="flex flex-1 overflow-hidden">
		<!-- Left: Mesh Grid -->
		<main class="flex flex-1 flex-col overflow-hidden">
			<ScrollArea class="flex-1 min-h-0">
				<div class="p-5 space-y-5 max-w-6xl mx-auto">
					<!-- Global Progress -->
					<GlobalProgress agents={allAgents} isRunning={isRunning} />

					<!-- Agent Mesh Grid -->
					<MeshGrid
						agents={allAgents}
						selectedId={agentRegistry.selectedAgentId}
						onSelect={(id) => agentRegistry.selectAgent(id)}
					/>

					<!-- Download -->
					{#if downloadReady && downloadData}
						<DownloadButtons
							projectName={downloadData.project_name}
							projectId={downloadData.project_id}
							zipUrl={downloadData.zip_url}
							dockerUrl={downloadData.docker_url}
						/>
					{/if}
				</div>
			</ScrollArea>

			<!-- Input Area -->
			<div class="mb-8 px-4 shrink-0 flex justify-center">
				<form
					class="flex w-full max-w-3xl items-center gap-2 rounded-[2.5rem] border border-white/60 bg-white/60 shadow-[0_8px_30px_rgb(0,0,0,0.06)] backdrop-blur-xl p-2.5 transition-all focus-within:bg-white/80 focus-within:shadow-[0_8px_40px_rgb(0,0,0,0.1)]"
					onsubmit={(e: SubmitEvent) => {
						e.preventDefault();
						handleSubmit();
					}}
				>
					<div class="relative flex-1 flex items-center">
						<Input
							bind:value={inputValue}
							placeholder="Describe your project... (e.g., Build a task manager with Spring Boot and Svelte)"
							disabled={isRunning}
							class="h-12 w-full border-0 bg-transparent px-5 text-[15px] shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50 text-foreground"
						/>
						{#if inputValue}
							<button
								type="button"
								class="absolute right-3 text-muted-foreground/40 hover:text-muted-foreground transition-colors p-1"
								onclick={() => inputValue = ''}
							>
								<span class="text-lg leading-none">&times;</span>
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
						{:else}
							<Send class="h-5 w-5 ml-0.5" />
						{/if}
					</Button>
				</form>
			</div>
		</main>

		<!-- Right: Agent Detail Panel -->
		{#if selectedAgent}
			<aside class="w-[420px] shrink-0 animate-fade-in">
				<AgentDetail
					agent={selectedAgent}
					onClose={() => agentRegistry.selectAgent(null)}
				/>
			</aside>
		{/if}
	</div>
</div>
