<script lang="ts">
	import FileTree from './FileTree.svelte';
	import MonacoEditor from './MonacoEditor.svelte';
	import AgentStatusPanel from './AgentStatusPanel.svelte';
	import type { EditorTab } from './MonacoEditor.svelte';
	import PanelRightClose from '@lucide/svelte/icons/panel-right-close';

	interface FileNode {
		name: string;
		path: string;
		type: 'file' | 'directory';
		children?: FileNode[];
	}

	interface AgentLike {
		id: string;
		name: string;
		status: 'idle' | 'working' | 'thinking' | 'complete' | 'error' | 'paused' | 'stopped';
		currentAction: string;
		progress: { percent: number; completed: number; total: number };
	}

	interface Props {
		files: FileNode[];
		projectId?: string;
		collapsed?: boolean;
		onToggleCollapse?: () => void;
		onSelectAgent?: (id: string) => void;
		selectedAgentId?: string | null;
		agents?: AgentLike[];
		lastWrittenFile?: { path: string; ts: number; content?: string; phase?: string };
	}

	let {
		files = [],
		projectId,
		collapsed = false,
		onToggleCollapse,
		onSelectAgent,
		selectedAgentId,
		agents = [],
		lastWrittenFile
	}: Props = $props();

	let openTabs = $state<EditorTab[]>([]);
	let activeTabPath = $state<string | undefined>(undefined);

	async function loadFileContent(path: string) {
		if (!projectId) return;
		try {
			const response = await fetch(`/api/workspace/${projectId}/read?path=${encodeURIComponent(path)}`);
			if (response.ok) {
				const data = await response.json();
				const content = typeof data.content === 'string' ? data.content : '';
				if (typeof data.content !== 'string') {
					console.error('Workspace read response did not include string content:', data);
				}
				const fileName = path.split('/').pop() || path;

				const existingTab = openTabs.find(t => t.path === path);
				if (existingTab) {
					// Always re-fetch — agent may have updated the file since it was first opened
					openTabs = openTabs.map(t =>
						t.path === path
							? { ...t, content, language: data.language || t.language }
							: t
					);
				} else {
					openTabs = [...openTabs, {
						path,
						name: fileName,
						content,
						language: data.language || 'plaintext'
					}];
				}
				activeTabPath = path;
			} else {
				const data = await response.json().catch(() => ({}));
				console.error('Failed to load file:', response.status, data);
			}
		} catch (error) {
			console.error('Failed to load file:', error);
		}
	}

	// Silently refresh open tab content when an agent writes to that file
	$effect(() => {
		if (!lastWrittenFile || !projectId) return;
		const { path, content, phase } = lastWrittenFile;
		const isOpen = openTabs.some(t => t.path === path);
		if (isOpen) {
			if (typeof content === 'string' && phase === 'preview') {
				openTabs = openTabs.map(t =>
					t.path === path
						? { ...t, content }
						: t
				);
				return;
			}
			loadFileContent(path);
		}
	});

	$effect(() => {
		if (openTabs.length > 0 && !activeTabPath) {
			activeTabPath = openTabs[0].path;
		}
	});

	function handleFileSelect(path: string) {
		loadFileContent(path);
	}

	function handleTabClose(path: string) {
		const newTabs = openTabs.filter(t => t.path !== path);
		openTabs = newTabs;
		if (activeTabPath === path) {
			activeTabPath = newTabs.length > 0 ? newTabs[newTabs.length - 1].path : undefined;
		}
	}
</script>

{#if !collapsed}
	<div class="ide">
		<!-- Window chrome -->
		<div class="ide-bar">
			<div class="dots">
				<span class="dot r"></span>
				<span class="dot y"></span>
				<span class="dot g"></span>
			</div>
			<span class="path">{projectId ? `project/${projectId.slice(0, 8)}` : 'project'}</span>
			<button onclick={onToggleCollapse} class="close-btn" title="Close">
				<PanelRightClose class="h-3.5 w-3.5" />
			</button>
		</div>

		<div class="ide-body">
			<!-- Tree -->
			<div class="ide-tree">
				<FileTree {files} onFileSelect={handleFileSelect} selectedPath={activeTabPath} />
			</div>

			<!-- Editor -->
			<div class="ide-editor">
				{#if openTabs.length > 0}
					<MonacoEditor
						tabs={openTabs}
						activeTab={activeTabPath}
						{projectId}
						onTabSelect={(path) => activeTabPath = path}
						onTabClose={handleTabClose}
						readOnly={true}
					/>
				{:else}
					<div class="empty-editor">
						<div class="empty-card">
							<p class="empty-title">Select a file</p>
							<p class="empty-sub">Open any file from the explorer to view and edit code.</p>
						</div>
					</div>
				{/if}
			</div>

			<!-- Agent status -->
			<div class="ide-side">
				<AgentStatusPanel {agents} onSelectAgent={onSelectAgent} {selectedAgentId} />
			</div>
		</div>
	</div>
{/if}

{#if collapsed}
	<button
		onclick={onToggleCollapse}
		class="code-peek-btn"
		title="Show code panel"
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
	</button>
{/if}

<style>
	.ide {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--ink-0);
		color: rgba(255,255,255,0.85);
		border: 1px solid rgba(255,255,255,0.08);
		box-shadow: 0 30px 80px rgba(20,18,32,0.18);
	}

	.ide-bar {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 14px;
		border-bottom: 1px solid rgba(255,255,255,0.06);
		background: rgba(255,255,255,0.03);
		font-family: var(--font-mono);
		font-size: 11px;
		color: rgba(255,255,255,0.45);
		flex-shrink: 0;
	}

	.dots {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: rgba(255,255,255,0.14);
	}
	.dot.r { background: oklch(70% 0.18 18); }
	.dot.y { background: oklch(80% 0.14 75); }
	.dot.g { background: oklch(75% 0.14 150); }

	.path {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.close-btn {
		background: none;
		border: none;
		padding: 4px;
		color: rgba(255,255,255,0.35);
		cursor: pointer;
		border-radius: 6px;
		line-height: 0;
		transition: color 120ms ease, background 120ms ease;
	}
	.close-btn:hover {
		color: rgba(255,255,255,0.70);
		background: rgba(255,255,255,0.06);
	}

	/* Body uses flex row (like original working layout) instead of grid */
	.ide-body {
		display: flex;
		flex-direction: row;
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	.ide-tree {
		width: 200px;
		flex-shrink: 0;
		border-right: 1px solid rgba(255,255,255,0.06);
		background: rgba(255,255,255,0.02);
		min-width: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.ide-editor {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		background: var(--ink-0);
		display: flex;
		flex-direction: column;
	}

	.ide-side {
		width: 220px;
		flex-shrink: 0;
		min-width: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.empty-editor {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		padding: 0 24px;
	}
	.empty-card {
		max-width: 280px;
		border-radius: 8px;
		border: 1px solid rgba(255,255,255,0.06);
		background: rgba(255,255,255,0.03);
		padding: 28px 24px;
		text-align: center;
	}
	.empty-title {
		font-size: 13px;
		font-weight: 500;
		color: rgba(255,255,255,0.70);
		margin: 0 0 6px;
	}
	.empty-sub {
		font-size: 11.5px;
		color: rgba(255,255,255,0.40);
		line-height: 1.5;
		margin: 0;
	}

	.code-peek-btn {
		position: fixed;
		right: 14px;
		top: 80px;
		z-index: 50;
		width: 36px;
		height: 36px;
		border-radius: 8px;
		border: 1px solid rgba(255,255,255,0.10);
		background: var(--ink-0);
		color: rgba(255,255,255,0.55);
		cursor: pointer;
		display: grid;
		place-items: center;
		box-shadow: 0 8px 24px rgba(20,18,32,0.25);
		transition: color 120ms ease, border-color 120ms ease, transform 120ms ease;
	}
	.code-peek-btn:hover {
		color: rgba(255,255,255,0.90);
		border-color: rgba(255,255,255,0.20);
		transform: translateY(-1px);
	}

	@media (max-width: 1280px) {
		.ide-tree { width: 180px; }
		.ide-side { width: 180px; }
	}

	@media (max-width: 1080px) {
		.ide-tree,
		.ide-side {
			display: none;
		}
	}
</style>
