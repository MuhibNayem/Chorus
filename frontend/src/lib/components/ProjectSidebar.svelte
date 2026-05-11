<script lang="ts">
	import { onMount } from 'svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import SearchIcon from '@lucide/svelte/icons/search';
	import Settings from '@lucide/svelte/icons/settings';
	import Loader2 from '@lucide/svelte/icons/loader-2';

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

	const activeProjects = $derived(filteredProjects.filter((p) => p.id === activeProjectId || p.status === 'running'));
	const recentProjects = $derived(filteredProjects.filter((p) => p.id !== activeProjectId && p.status !== 'running'));

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

	function getProjectIndex(project: any): string {
		const idx = projects.findIndex((p) => p.id === project.id);
		return String(idx + 1).padStart(2, '0');
	}

	function getProjectMeta(project: any): string {
		if (project.status === 'running') return 'CONDUCTING · LIVE';
		if (project.status === 'complete') return 'SHIPPED';
		if (project.status === 'archived') return 'ARCHIVED';
		return (project.status || 'IDLE').toUpperCase();
	}
</script>

<aside class="side">
	<div class="brand full">
		<span class="hex-mark"><svg viewBox="0 0 32 32" fill="none">
			<path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z"/>
			<path d="M16 9 L22 12.5 L22 19.5 L16 23 L10 19.5 L10 12.5 Z" fill="white"/>
		</svg></span>
		Chorus
	</div>

	<button class="new full" onclick={handleNewProject}>
		<Plus size={14} strokeWidth={2.5} />
		<span>New project</span>
		<kbd>⌘N</kbd>
	</button>

	<div class="search full">
		<SearchIcon size={14} strokeWidth={2} />
		<input placeholder="Search projects" bind:value={searchQuery} />
	</div>

	{#if activeProjects.length > 0}
		<h5 class="full">Active</h5>
		{#each activeProjects as project (project.id)}
			<button 
				type="button"
				class="proj full {project.id === activeProjectId ? 'active' : ''}"
				onclick={() => onSelect(project.id)}
			>
				<div class="row1">
					<span class="ix">{getProjectIndex(project)}</span>
					<span class="nm">{project.name || 'Untitled'}</span>
					{#if project.id === activeProjectId}
						<span class="live"></span>
					{/if}
				</div>
				<span class="meta">{getProjectMeta(project)}</span>
			</button>
		{/each}
	{/if}

	{#if recentProjects.length > 0}
		<h5 class="full">Recent</h5>
		{#each recentProjects as project (project.id)}
			<button 
				type="button"
				class="proj full {project.id === activeProjectId ? 'active' : ''}"
				onclick={() => onSelect(project.id)}
			>
				<div class="row1">
					<span class="ix">{getProjectIndex(project)}</span>
					<span class="nm">{project.name || 'Untitled'}</span>
				</div>
				<span class="meta">{getProjectMeta(project)} · {new Date(project.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }).toUpperCase()}</span>
			</button>
		{/each}
	{/if}

	{#if loading}
		<div class="full" style="display: flex; justify-content: center; padding: 16px 0;">
			<Loader2 size={16} class="animate-spin" style="color: var(--ink-5);" />
		</div>
	{/if}

	{#if !loading && projects.length === 0}
		<div class="full" style="padding: 24px 8px; text-align: center; color: var(--ink-5); font-size: 12px;">
			No projects yet
		</div>
	{/if}

	<div class="me full">
		<span class="av"></span>
		<div class="info">
			<b>Chorus User</b>
			<span>STUDIO · {projects.filter(p => p.status === 'running').length} ACTIVE</span>
		</div>
		<a href="/settings" title="Settings">
			<Settings size={14} strokeWidth={2} />
		</a>
	</div>
</aside>

{#if isMobile && !isCollapsed}
	<button
		type="button"
		onclick={onToggle}
		onkeydown={(e) => e.key === 'Escape' && onToggle()}
		class="mobile-overlay"
		aria-label="Close sidebar"
	></button>
{/if}

<style>
	.side {
		width: 260px;
		flex-shrink: 0;
		background: var(--paper-0);
		border-right: 1px solid var(--line);
		display: flex; flex-direction: column;
		padding: 18px 14px;
		overflow-y: auto;
		height: 100%;
	}
	.brand {
		display: flex; align-items: center; gap: 10px; padding: 4px 6px 18px;
		font-weight: 600; letter-spacing: -0.01em;
		color: var(--ink-0); font-size: 15px;
	}
	.hex-mark svg { width: 28px; height: 28px; display: block; }
	.hex-mark svg path:first-child { fill: url(#g-vio); }
	.new {
		display: flex; align-items: center; gap: 10px;
		padding: 11px 12px; border-radius: 12px;
		background: var(--ink-0); color: white;
		font-size: 13px; font-weight: 500;
		cursor: pointer; border: 0;
		box-shadow: 0 6px 18px rgba(124,58,237,0.18), inset 0 1px 0 rgba(255,255,255,0.10);
		margin-bottom: 18px;
		transition: transform 200ms ease;
		position: relative; overflow: hidden;
	}
	.new::before {
		content: ""; position: absolute; inset: 0;
		background: linear-gradient(180deg, oklch(70% 0.18 295 / 0.20), transparent 60%);
	}
	.new:hover { transform: translateY(-1px); }
	.new :global(svg), .new span, .new kbd { position: relative; z-index: 1; }
	.new kbd {
		margin-left: auto;
		font-family: var(--font-mono); font-size: 10px;
		background: rgba(255,255,255,0.10);
		padding: 3px 6px; border-radius: 5px;
		letter-spacing: 0.05em;
	}
	.search {
		display: flex; align-items: center; gap: 8px;
		background: var(--paper-1); border: 1px solid var(--line);
		border-radius: 11px; padding: 8px 11px;
		margin-bottom: 14px;
	}
	.search :global(svg) { color: var(--ink-5); flex-shrink: 0; }
	.search input {
		border: 0; background: transparent;
		font-family: inherit; font-size: 13px;
		flex: 1; color: var(--ink-1); outline: none;
	}
	.search input::placeholder { color: var(--ink-5); }

	h5 {
		font-family: var(--font-mono); font-size: 10.5px;
		letter-spacing: 0.14em; text-transform: uppercase;
		color: var(--ink-5); margin: 14px 8px 6px; font-weight: 500;
	}

	.proj {
		display: flex; flex-direction: column;
		padding: 9px 11px; border-radius: 11px;
		cursor: pointer; transition: all 160ms ease;
		border: 1px solid transparent;
		margin-bottom: 1px;
		position: relative;
		background: transparent;
		text-align: left;
		width: 100%;
	}
	.proj:hover { background: var(--paper-1); }
	.proj.active {
		background: var(--paper-1);
		border-color: var(--line);
		box-shadow: 0 1px 3px rgba(20,18,32,0.04);
	}
	.proj.active::before {
		content: ""; position: absolute; left: -1px; top: 12px; bottom: 12px;
		width: 2.5px; background: var(--violet-d); border-radius: 0 2px 2px 0;
	}
	.proj .row1 { display: flex; align-items: center; gap: 7px; }
	.proj .ix {
		font-family: var(--font-mono); font-size: 10px;
		color: var(--ink-5); letter-spacing: 0.06em;
	}
	.proj .nm {
		font-size: 13px; font-weight: 500; color: var(--ink-1);
		white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
		flex: 1;
	}
	.proj .live {
		width: 6px; height: 6px; border-radius: 50%;
		background: var(--violet);
		box-shadow: 0 0 8px var(--violet);
		animation: pulse 1.4s ease-in-out infinite;
	}
	.proj .meta {
		font-family: var(--font-mono); font-size: 10px;
		color: var(--ink-5); letter-spacing: 0.06em;
		margin-top: 3px; padding-left: 2px;
	}
	@keyframes pulse {
		0%,100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.4; transform: scale(1.2); }
	}

	.me {
		margin-top: auto; padding: 11px;
		border: 1px solid var(--line); border-radius: 13px;
		background: var(--paper-1);
		display: flex; gap: 10px; align-items: center;
	}
	.me .av {
		width: 30px; height: 30px; border-radius: 50%;
		background: conic-gradient(from 130deg, oklch(70% 0.18 295), oklch(75% 0.15 220), oklch(78% 0.18 30));
		flex-shrink: 0;
	}
	.me .info { flex: 1; min-width: 0; }
	.me .info b { font-size: 12.5px; font-weight: 500; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--ink-0); }
	.me .info span { font-size: 10.5px; color: var(--ink-5); font-family: var(--font-mono); letter-spacing: 0.04em; }
	.me a { color: var(--ink-5); padding: 4px; border-radius: 6px; display: inline-flex; }
	.me a:hover { background: var(--paper-2); color: var(--ink-1); }

	.mobile-overlay {
		position: fixed; inset: 0; background: rgba(0,0,0,0.20);
		backdrop-filter: blur(4px); z-index: 30;
		border: 0; padding: 0; cursor: default;
	}

	@media (max-width: 768px) {
		.side {
			width: 100% !important;
			height: auto;
			border-right: none;
			border-bottom: 1px solid var(--line);
			flex-direction: row;
			flex-wrap: wrap;
			padding: 12px;
			gap: 8px;
		}
		.me { margin-top: 0; }
	}
</style>
