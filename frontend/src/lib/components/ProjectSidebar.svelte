<script lang="ts">
	import { onMount } from 'svelte';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import { Badge } from '$lib/components/ui/badge';
	import { cn } from '$lib/utils';
	import Plus from '@lucide/svelte/icons/plus';
	import History from '@lucide/svelte/icons/history';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import Search from '@lucide/svelte/icons/search';
	import PanelLeftClose from '@lucide/svelte/icons/panel-left-close';
	import PanelLeftOpen from '@lucide/svelte/icons/panel-left-open';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Layers3 from '@lucide/svelte/icons/layers-3';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';

	let { 
		activeProjectId, 
		isCollapsed = $bindable(false),
		isMobile = false,
		onToggle,
		onSelect, 
		onNew,
		onDelete
	}: { 
		activeProjectId: string | null; 
		isCollapsed: boolean;
		isMobile: boolean;
		onToggle: () => void;
		onSelect: (id: string) => void;
		onNew: () => void | Promise<void>;
		onDelete: (id: string) => void | Promise<void>;
	} = $props();

	let projects = $state<any[]>([]);
	let searchQuery = $state('');
	let loading = $state(false);
	let hasMore = $state(true);
	let offset = $state(0);
	let deletingId = $state<string | null>(null);
	let confirmDeleteId = $state<string | null>(null);
	const limit = 20;
	const avatarTones = [
		'from-sky-500/90 to-cyan-500/80 text-white',
		'from-emerald-500/90 to-teal-500/80 text-white',
		'from-violet-500/90 to-fuchsia-500/80 text-white',
		'from-amber-500/90 to-orange-500/80 text-white',
		'from-slate-700 to-slate-900 text-white',
		'from-rose-500/90 to-pink-500/80 text-white'
	];

	const filteredProjects = $derived(
		projects.filter((project) => {
			if (!searchQuery.trim()) return true;
			const query = searchQuery.toLowerCase();
			return (
				(project.name || '').toLowerCase().includes(query) ||
				(project.status || '').toLowerCase().includes(query) ||
				(project.spec?.message || '').toLowerCase().includes(query)
			);
		})
	);

	async function fetchProjects(reset = false) {
		if (loading || (!hasMore && !reset)) return;
		
		loading = true;
		if (reset) {
			offset = 0;
			projects = [];
			hasMore = true;
		}

		try {
			const res = await fetch(`/api/projects?limit=${limit}&offset=${offset}`);
			if (res.ok) {
				const data = await res.json();
				const newProjects = data.projects || [];
				
				projects = [...projects, ...newProjects];
				offset += limit;
				hasMore = newProjects.length === limit;
			}
		} catch (e) {
			console.error('Failed to fetch projects:', e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchProjects(true);
	});

	function handleScroll(e: Event) {
		const target = e.target as HTMLElement;
		const bottom = target.scrollHeight - target.scrollTop <= target.clientHeight + 100;
		if (bottom && !loading && hasMore) {
			fetchProjects();
		}
	}

	function toggleSidebar() {
		onToggle();
	}

	function handleNewProject() {
		void (async () => {
			await onNew();
			await fetchProjects(true);
		})();
	}

	async function handleDeleteProject(projectId: string) {
		if (confirmDeleteId !== projectId) {
			confirmDeleteId = projectId;
			return;
		}
		confirmDeleteId = null;
		deletingId = projectId;
		try {
			await onDelete(projectId);
			projects = projects.filter((p) => p.id !== projectId);
		} catch (e) {
			console.error('Failed to delete project:', e);
		} finally {
			deletingId = null;
		}
	}

	function cancelDelete() {
		confirmDeleteId = null;
	}

	function hashString(value: string): number {
		let hash = 0;
		for (let i = 0; i < value.length; i += 1) {
			hash = (hash * 31 + value.charCodeAt(i)) | 0;
		}
		return Math.abs(hash);
	}

	function getProjectAvatarTone(project: any): string {
		const key = project.id || project.name || 'project';
		return avatarTones[hashString(key) % avatarTones.length];
	}
</script>

<aside 
	class={cn(
		"relative flex h-full min-h-0 flex-col overflow-hidden border-r border-white/40 bg-[linear-gradient(180deg,rgba(255,255,255,0.72),rgba(248,250,252,0.54)_38%,rgba(239,246,255,0.5))] shadow-[0_24px_60px_rgba(15,23,42,0.14)] backdrop-blur-2xl transition-all duration-300 ease-out z-40",
		isCollapsed ? (isMobile ? "w-0 border-none -translate-x-full opacity-0" : "w-20") : "w-[18rem]",
		isMobile && !isCollapsed ? "fixed inset-y-0 left-0 w-72 translate-x-0" : ""
	)}
>
	<!-- Header / Actions -->
	<div class="shrink-0 p-3">
		<div class="rounded-[1.5rem] border border-white/50 bg-white/45 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] backdrop-blur-xl">
			{#if isCollapsed && !isMobile}
				<div class="flex flex-col items-center gap-2">
					<button
						onclick={toggleSidebar}
						class="group flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/50 bg-white/55 text-muted-foreground shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-white hover:text-slate-900 hover:shadow-md"
						title="Expand Sidebar"
					>
						<PanelLeftOpen class="h-4.5 w-4.5 transition-transform duration-200 group-hover:scale-110" />
					</button>
					<button
						onclick={handleNewProject}
						class="group flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-cyan-200/55 bg-white/60 text-cyan-700 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-white hover:shadow-md"
						title="New Project"
					>
						<Plus class="h-4 w-4 transition-transform duration-200 group-hover:scale-110" />
					</button>
				</div>
			{:else}
				<div class="flex items-center gap-2 justify-between">
					<button
						onclick={handleNewProject}
						class="group flex h-10 flex-1 items-center justify-center gap-2 rounded-xl border border-cyan-200/55 bg-white/60 px-3 text-cyan-700 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-white hover:shadow-md"
						title="New Project"
					>
						<Plus class="h-4 w-4 transition-transform duration-200 group-hover:scale-110" />
						<span class="text-[11px] font-semibold tracking-wide">New Project</span>
					</button>
					<button 
						onclick={toggleSidebar}
						class="group flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/50 bg-white/55 text-muted-foreground shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-white hover:text-slate-900 hover:shadow-md"
						title="Collapse Sidebar"
					>
						<PanelLeftClose class="h-4.5 w-4.5 transition-transform duration-200 group-hover:scale-110" />
					</button>
				</div>
			{/if}

			{#if !isCollapsed}
				<div class="mt-3 flex items-center gap-3">
					<div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[linear-gradient(145deg,rgba(14,165,233,0.92),rgba(20,184,166,0.82))] text-white shadow-[0_12px_24px_rgba(14,165,233,0.18)]">
						<Layers3 class="h-5 w-5" />
					</div>
					<div class="min-w-0 flex-1">
						<p class="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground/55">Workspace</p>
						<p class="truncate text-sm font-semibold text-slate-900">Project archive</p>
					</div>
				</div>

				<div class="mt-3 rounded-2xl border border-white/50 bg-white/55 p-2 shadow-sm backdrop-blur-xl">
					<div class="relative">
						<Search class="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/45" />
						<input
							bind:value={searchQuery}
							placeholder="Search projects"
							class="h-10 w-full rounded-xl border border-transparent bg-white/70 pl-9 pr-3 text-xs text-slate-700 outline-none transition-all placeholder:text-muted-foreground/35 focus:bg-white focus:ring-1 focus:ring-primary/20"
						/>
					</div>
				</div>

				<div class="mt-3 grid grid-cols-2 gap-2">
					<div class="rounded-2xl border border-white/50 bg-white/45 px-3 py-2 shadow-sm">
						<p class="text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground/45">Recent</p>
						<p class="mt-1 text-sm font-semibold text-slate-900">{projects.length}</p>
					</div>
					<div class="rounded-2xl border border-white/50 bg-white/45 px-3 py-2 shadow-sm">
						<p class="text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground/45">Active</p>
						<p class="mt-1 text-sm font-semibold text-slate-900">{activeProjectId ? '1' : '0'}</p>
					</div>
				</div>

				<div class="mt-3 flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground/45">
					<span>Recent Projects</span>
					<span class="inline-flex items-center gap-1 text-primary/70">
						<Sparkles class="h-3 w-3" />
						Live
					</span>
				</div>
			{/if}
		</div>
	</div>

	<!-- Project List -->
	<ScrollArea
		class="min-h-0 flex-1"
		onscroll={handleScroll}
		scrollbarYClasses="w-2.5 bg-white/30 p-[2px] border-l border-white/50"
	>
		<div class={cn(
			"flex h-full min-h-0 flex-col pb-2",
			isCollapsed ? "items-center px-0 pt-2" : "px-2"
		)}>
			{#each filteredProjects as project, index (project.id)}
					{#if isCollapsed}
						<button
							onclick={() => onSelect(project.id)}
							class={cn(
								"sidebar-row group relative mb-2 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md mx-auto",
								activeProjectId === project.id
									? "border-white/70 bg-white/75 text-primary shadow-[0_10px_20px_rgba(15,23,42,0.10)]"
									: "border-white/35 bg-white/35 text-muted-foreground/60 hover:bg-white/60"
							)}
							title={project.name || 'Untitled'}
							style={`animation-delay: ${index * 40}ms`}
						>
							<div class={cn(
								"flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br text-[10px] font-bold tracking-[0.08em] shadow-[0_8px_18px_rgba(15,23,42,0.10)] transition-transform duration-200 group-hover:scale-105",
								getProjectAvatarTone(project)
							)}>
								<svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
									<rect x="5" y="5" width="5.5" height="5.5" rx="1.6" fill="currentColor" fill-opacity="0.95" />
									<rect x="13.5" y="5" width="5.5" height="5.5" rx="1.6" fill="currentColor" fill-opacity="0.75" />
									<rect x="9.25" y="13.5" width="5.5" height="5.5" rx="1.6" fill="currentColor" fill-opacity="0.88" />
								</svg>
							</div>
							{#if activeProjectId === project.id}
								<div class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-white bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.45)]"></div>
							{/if}
						</button>
					{:else}
						<div
							class={cn(
								"sidebar-row group relative mb-2 w-full overflow-hidden rounded-2xl border p-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:bg-white/60 hover:shadow-[0_12px_26px_rgba(15,23,42,0.08)]",
								activeProjectId === project.id ? "border-white/70 bg-white/75 shadow-[0_14px_28px_rgba(15,23,42,0.10)]" : "border-white/30 bg-white/30"
							)}
							style={`animation-delay: ${index * 40}ms`}
						>
							<button
								onclick={() => onSelect(project.id)}
								class="w-full text-left"
							>
								<div class="min-w-0 flex-1">
									<div class="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/80 to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100"></div>
									<div class="flex items-center justify-between gap-2 overflow-hidden">
										<span class={cn(
											"truncate text-[13px] font-semibold tracking-tight transition-colors",
											activeProjectId === project.id ? "text-slate-900" : "text-slate-700"
										)}>
											{project.name || 'Untitled'}
										</span>
										<Badge variant={project.status === 'complete' ? 'default' : 'outline'} class="text-[9px] h-4 px-1.5 uppercase leading-none font-bold shrink-0 rounded-full">
											{project.status}
										</Badge>
									</div>
									<p class="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground/60">
										{project.spec?.message || 'No description'}
									</p>
								</div>
							</button>
							<div class="mt-2 flex items-center justify-between">
								<span class="text-[9px] text-muted-foreground/45">
									{new Date(project.updated_at).toLocaleDateString()}
								</span>
								<div class="flex items-center gap-1">
									{#if confirmDeleteId === project.id}
										<div class="flex items-center gap-1 animate-in fade-in zoom-in duration-200">
											<span class="text-[9px] font-semibold text-rose-600">Confirm?</span>
											<button
												onclick={() => handleDeleteProject(project.id)}
												class="flex h-6 w-6 items-center justify-center rounded-lg bg-rose-500 text-white shadow-sm hover:bg-rose-600 transition-colors"
												title="Confirm delete"
												>
												{#if deletingId === project.id}
													<Loader2 class="h-3 w-3 animate-spin" />
												{:else}
													<Trash2 class="h-3 w-3" />
												{/if}
											</button>
											<button
												onclick={cancelDelete}
												class="flex h-6 w-6 items-center justify-center rounded-lg bg-white/70 text-muted-foreground shadow-sm hover:bg-white transition-colors"
												title="Cancel"
												>
												<span class="text-[10px] font-bold">×</span>
											</button>
										</div>
									{:else}
										<button
											onclick={() => handleDeleteProject(project.id)}
											class="flex h-6 w-6 items-center justify-center rounded-lg text-muted-foreground/40 opacity-0 transition-all duration-200 hover:bg-rose-50 hover:text-rose-500 group-hover:opacity-100"
											title="Delete project"
											>
											<Trash2 class="h-3 w-3" />
										</button>
									{/if}
									<ArrowUpRight class="h-3 w-3 text-primary/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
								</div>
							</div>

							{#if activeProjectId === project.id}
								<div class="absolute left-0 top-3 h-[calc(100%-1.5rem)] w-1 rounded-r-full bg-gradient-to-b from-cyan-400 via-sky-500 to-teal-400"></div>
							{/if}
						</div>
				{/if}
			{/each}

			{#if loading}
				<div class="flex justify-center py-4">
					<Loader2 class="h-5 w-5 animate-spin text-muted-foreground/40" />
				</div>
			{/if}

			{#if !loading && projects.length === 0 && !isCollapsed}
				<div class="flex-1 flex flex-col items-center justify-center py-20 text-center animate-in fade-in zoom-in duration-700">
					<div class="relative mb-4">
						<div class="absolute -inset-4 rounded-full bg-primary/5 blur-xl animate-pulse"></div>
						<div class="relative flex h-16 w-16 items-center justify-center rounded-[1.25rem] border border-white/55 bg-white/45 shadow-[0_12px_28px_rgba(15,23,42,0.08)] backdrop-blur-sm">
							<History class="h-8 w-8 text-muted-foreground/25" />
						</div>
					</div>
					<h3 class="text-xs font-bold text-foreground/40 uppercase tracking-widest mb-1">No History</h3>
					<p class="text-[10px] text-muted-foreground/40 max-w-[140px] leading-relaxed">
						Your generated projects will appear here.
					</p>
				</div>
			{/if}
		</div>
	</ScrollArea>

	<!-- Bottom Section -->
	<div class="mt-auto shrink-0 border-t border-white/35 p-3">
		{#if isCollapsed}
			<div class="flex h-10 w-10 items-center justify-center rounded-xl border border-white/50 bg-white/55 font-bold text-primary text-xs shadow-sm">
				CH
			</div>
		{:else}
			<div class="flex items-center gap-3 rounded-[1.25rem] border border-white/50 bg-white/45 p-3 shadow-sm animate-in fade-in duration-500">
				<div class="flex h-9 w-9 items-center justify-center rounded-xl bg-[linear-gradient(145deg,rgba(14,165,233,0.9),rgba(20,184,166,0.8))] border border-white/50 text-white font-bold text-xs shadow-[0_10px_20px_rgba(14,165,233,0.14)]">
					CH
				</div>
				<div class="flex flex-col overflow-hidden">
					<span class="text-[11px] font-bold truncate text-slate-900">Chorus Pro</span>
					<span class="text-[9px] text-muted-foreground/60">Parallel Mesh Active</span>
				</div>
			</div>
		{/if}
	</div>
</aside>

<!-- Mobile Overlay -->
{#if isMobile && !isCollapsed}
	<button
		type="button"
		onclick={toggleSidebar}
		onkeydown={(e) => e.key === 'Escape' && toggleSidebar()}
		class="fixed inset-0 bg-black/20 backdrop-blur-sm z-30 transition-opacity duration-300 cursor-default"
		aria-label="Close sidebar"
	></button>
{/if}

<style>
	@keyframes sidebarRowIn {
		from {
			opacity: 0;
			transform: translateY(8px) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}

	.sidebar-row {
		animation: sidebarRowIn 420ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
	}
</style>
