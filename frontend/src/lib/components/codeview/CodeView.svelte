<script lang="ts">
	import FileTree from './FileTree.svelte';
	import MonacoEditor from './MonacoEditor.svelte';
	import type { EditorTab } from './MonacoEditor.svelte';
	import Code2 from '@lucide/svelte/icons/code-2';
	import PanelRightClose from '@lucide/svelte/icons/panel-right-close';
	import PanelRight from '@lucide/svelte/icons/panel-right';

	interface FileNode {
		name: string;
		path: string;
		type: 'file' | 'directory';
		children?: FileNode[];
	}

	interface Props {
		files: FileNode[];
		projectId?: string;
		collapsed?: boolean;
		onToggleCollapse?: () => void;
		lastWrittenFile?: { path: string; ts: number; content?: string; phase?: string };
	}

	let { files = [], projectId, collapsed = false, onToggleCollapse, lastWrittenFile }: Props = $props();

	let openTabs = $state<EditorTab[]>([]);
	let activeTabPath = $state<string | undefined>(undefined);

	async function loadFileContent(path: string) {
		if (!projectId) return;
		try {
			const response = await fetch(`/api/workspace/${projectId}/read?path=${encodeURIComponent(path)}`);
			if (response.ok) {
				const data = await response.json();
				const fileName = path.split('/').pop() || path;

				const existingTab = openTabs.find(t => t.path === path);
				if (existingTab) {
					// Always re-fetch — agent may have updated the file since it was first opened
					openTabs = openTabs.map(t =>
						t.path === path
							? { ...t, content: data.content, language: data.language || t.language }
							: t
					);
				} else {
					openTabs = [...openTabs, {
						path,
						name: fileName,
						content: data.content,
						language: data.language || 'plaintext'
					}];
				}
				activeTabPath = path;
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
	<div class="flex h-full min-h-0 overflow-hidden rounded-[2rem] border border-white/50 bg-white/65 shadow-[0_20px_60px_rgba(15,23,42,0.12)] backdrop-blur-xl">
		<!-- Explorer -->
		<div class="flex w-72 xl:w-80 min-h-0 flex-col border-r border-white/40 bg-white/40">
			<div class="flex items-start justify-between gap-3 border-b border-white/40 px-4 py-4">
				<div class="space-y-1">
					<div class="flex items-center gap-2">
						<Code2 class="h-4 w-4 text-primary" />
						<span class="text-sm font-semibold text-foreground">Explorer</span>
					</div>
					<p class="text-[11px] leading-4 text-muted-foreground/65">
						VS Code style file browser with unlimited nesting.
					</p>
				</div>
				<button
					onclick={onToggleCollapse}
					class="rounded-xl border border-white/40 bg-white/50 p-2 shadow-sm transition-colors hover:bg-white hover:text-foreground"
					title="Collapse panel"
				>
					<PanelRightClose class="h-4 w-4 text-muted-foreground/60" />
				</button>
			</div>

			<div class="min-h-0 flex-1 overflow-visible">
				<FileTree
					{files}
					onFileSelect={handleFileSelect}
					selectedPath={activeTabPath}
				/>
			</div>
		</div>

		<!-- Editor -->
		<div class="min-h-0 flex-1 bg-editor/95">
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
				<div class="flex h-full items-center justify-center px-8">
					<div class="max-w-sm rounded-2xl border border-white/10 bg-white/5 px-6 py-8 text-center text-muted-foreground/60 shadow-lg shadow-black/10">
						<div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10">
							<Code2 class="h-7 w-7 text-primary" />
						</div>
						<p class="text-sm font-medium text-foreground/85">Select a file from the explorer</p>
						<p class="mt-2 text-xs leading-5">
							The editor opens beside the tree, matching the VS Code layout and keeping deeper folders accessible.
						</p>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}

{#if collapsed}
	<button
		onclick={onToggleCollapse}
		class="fixed right-4 top-20 rounded-xl border border-white/40 bg-white/80 p-2 shadow-lg shadow-black/10 backdrop-blur-xl transition-colors hover:bg-white z-50"
		title="Show code panel"
	>
		<PanelRight class="h-5 w-5 text-primary" />
	</button>
{/if}
