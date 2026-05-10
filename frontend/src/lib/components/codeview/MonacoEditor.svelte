<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Download from '@lucide/svelte/icons/download';
	import Copy from '@lucide/svelte/icons/copy';
	import Check from '@lucide/svelte/icons/check';
	import FolderArchive from '@lucide/svelte/icons/folder-archive';
	import type * as Monaco from 'monaco-editor';
	import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
	import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';
	import CssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker';
	import HtmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker';
	import TsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';

	export interface EditorTab {
		path: string;
		name: string;
		content: string;
		language: string;
	}

	interface Props {
		tabs: EditorTab[];
		activeTab?: string;
		projectId?: string;
		onTabClose?: (path: string) => void;
		onTabSelect?: (path: string) => void;
		onSave?: (path: string, content: string) => void;
		readOnly?: boolean;
	}

	let { tabs = [], activeTab, projectId, onTabClose, onTabSelect, onSave, readOnly = true }: Props = $props();

	let editorContainer: HTMLDivElement;
	let editor = $state<Monaco.editor.IStandaloneCodeEditor | null>(null);
	let monaco = $state<typeof Monaco | null>(null);
	let copied = $state(false);
	let currentContent = $state('');
	let currentModel: Monaco.editor.ITextModel | null = null;

	type MonacoEnvironmentWindow = Window & {
		MonacoEnvironment?: {
			getWorker?: (_moduleId: string, label: string) => Worker;
		};
	};

	function getLanguage(filename: string): string {
		const ext = filename.split('.').pop()?.toLowerCase() || '';
		const langMap: Record<string, string> = {
			'java': 'java',
			'svelte': 'html',
			'ts': 'typescript',
			'js': 'javascript',
			'json': 'json',
			'yml': 'yaml',
			'yaml': 'yaml',
			'xml': 'xml',
			'properties': 'properties',
			'gradle': 'groovy',
			'md': 'markdown',
			'css': 'css',
			'html': 'html',
			'txt': 'plaintext',
			'py': 'python',
			'sh': 'shell',
			'bash': 'shell'
		};
		return langMap[ext] || 'plaintext';
	}

	async function initMonaco() {
		(window as MonacoEnvironmentWindow).MonacoEnvironment = {
			getWorker(_moduleId: string, label: string) {
				if (label === 'json') return new JsonWorker();
				if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker();
				if (label === 'html' || label === 'handlebars' || label === 'razor') return new HtmlWorker();
				if (label === 'typescript' || label === 'javascript') return new TsWorker();
				return new EditorWorker();
			}
		};

		const monacoModule = await import('monaco-editor');
		monaco = monacoModule;

		monaco.editor.defineTheme('chorus-dark', {
			base: 'vs-dark',
			inherit: true,
			rules: [
				{ token: 'comment', foreground: '6A9955' },
				{ token: 'keyword', foreground: '569CD6' },
				{ token: 'string', foreground: 'CE9178' },
				{ token: 'number', foreground: 'B5CEA8' },
				{ token: 'type', foreground: '4EC9B0' }
			],
			colors: {
				'editor.background': '#0d1117',
				'editor.foreground': '#c9d1d9',
				'editor.lineHighlightBackground': '#161b22',
				'editor.selectionBackground': '#264f78',
				'editorCursor.foreground': '#58A6FF',
				'editorLineNumber.foreground': '#484f58',
				'editorLineNumber.activeForeground': '#c9d1d9'
			}
		});

		editor = monaco.editor.create(editorContainer, {
			value: currentContent,
			language: 'plaintext',
			theme: 'chorus-dark',
			readOnly: readOnly,
			minimap: { enabled: false },
			fontSize: 13,
			fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
			lineNumbers: 'on',
			scrollBeyondLastLine: false,
			renderLineHighlight: 'line',
			padding: { top: 12, bottom: 12 },
			automaticLayout: true,
			tabSize: 4,
			wordWrap: 'on',
			scrollbar: {
				verticalScrollbarSize: 8,
				horizontalScrollbarSize: 8
			}
		});

		if (!readOnly) {
			editor.onDidChangeModelContent(() => {
				const value = editor?.getValue() || '';
				currentContent = value;
			});
		}

		const initialTab = tabs.find((tab) => tab.path === activeTab) || tabs[0];
		if (initialTab) {
			loadTab(initialTab);
		}
	}

	function loadTab(tab: EditorTab) {
		if (!editor || !monaco) return;

		currentModel?.dispose();
		const model = monaco.editor.createModel(
			tab.content,
			getLanguage(tab.name)
		);

		currentModel = model;
		editor.setModel(model);
		currentContent = tab.content;
	}

	$effect(() => {
		if (editor && monaco && activeTab) {
			const tab = tabs.find((t) => t.path === activeTab);
			if (tab) {
				loadTab(tab);
			}
		}
	});

	export function getContent(): string {
		return editor?.getValue() || '';
	}

	export function setContent(content: string, language: string = 'plaintext') {
		if (!editor || !monaco) return;
		currentModel?.dispose();
		const model = monaco.editor.createModel(content, language);
		currentModel = model;
		editor.setModel(model);
		currentContent = content;
	}

	async function copyContent() {
		const content = editor?.getValue() || '';
		await navigator.clipboard.writeText(content);
		copied = true;
		setTimeout(() => copied = false, 2000);
	}

	function downloadFile() {
		if (!activeTab) return;
		const tab = tabs.find(t => t.path === activeTab);
		if (!tab) return;

		const blob = new Blob([tab.content], { type: 'text/plain' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = tab.name;
		a.click();
		URL.revokeObjectURL(url);
	}

	async function downloadProjectZip() {
		if (!projectId) return;
		try {
			const response = await fetch(`/api/download/${projectId}/project.zip`);
			if (!response.ok) {
				throw new Error(`HTTP ${response.status}`);
			}
			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `project_${projectId.slice(0, 8)}.zip`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (error) {
			console.error('Failed to download project ZIP:', error);
		}
	}

	onMount(() => {
		initMonaco();
	});

	onDestroy(() => {
		currentModel?.dispose();
		editor?.dispose();
	});
</script>

<div class="flex flex-col h-full bg-editor">
	<!-- Tabs -->
	{#if tabs.length > 0}
		<div class="flex items-center bg-sidebar border-b border-white/10 overflow-x-auto">
			{#each tabs as tab (tab.path)}
				<button
					type="button"
					class="group flex items-center gap-2 px-3 py-2 text-xs border-r border-white/5 cursor-pointer transition-colors {activeTab === tab.path ? 'bg-editor text-foreground' : 'bg-sidebar text-muted-foreground/70 hover:bg-white/5 hover:text-foreground/80'}"
					onclick={() => {
						onTabSelect?.(tab.path);
						loadTab(tab);
					}}
					role="tab"
					aria-selected={activeTab === tab.path}
				>
					<span class="truncate max-w-[150px]">{tab.name}</span>
					{#if onTabClose}
						<span
							onclick={(e) => { e.stopPropagation(); onTabClose?.(tab.path); }}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onTabClose?.(tab.path); }}}
							class="opacity-0 group-hover:opacity-100 hover:bg-white/10 rounded p-0.5 transition-opacity cursor-pointer"
							role="button"
							tabindex="0"
						>
							<X class="h-3 w-3" />
						</span>
					{/if}
				</button>
			{/each}
		</div>
	{/if}

	<!-- Toolbar -->
	<div class="flex items-center gap-2 px-3 py-1.5 border-b border-white/5 bg-sidebar/50">
		<button
			onclick={copyContent}
			class="flex items-center gap-1.5 px-2 py-1 text-xs text-muted-foreground/70 hover:text-foreground hover:bg-white/5 rounded transition-colors"
			title="Copy content"
		>
			{#if copied}
				<Check class="h-3.5 w-3.5 text-green-500" />
				<span>Copied!</span>
			{:else}
				<Copy class="h-3.5 w-3.5" />
				<span>Copy</span>
			{/if}
		</button>
		<button
			onclick={downloadFile}
			class="flex items-center gap-1.5 px-2 py-1 text-xs text-muted-foreground/70 hover:text-foreground hover:bg-white/5 rounded transition-colors"
			title="Download file"
		>
			<Download class="h-3.5 w-3.5" />
			<span>Download</span>
		</button>
		<button
			onclick={downloadProjectZip}
			disabled={!projectId}
			class="flex items-center gap-1.5 px-2 py-1 text-xs text-muted-foreground/70 hover:text-foreground hover:bg-white/5 rounded transition-colors disabled:opacity-50"
			title="Download project ZIP"
		>
			<FolderArchive class="h-3.5 w-3.5" />
			<span>Project ZIP</span>
		</button>
		<div class="flex-1"></div>
		{#if activeTab}
			<span class="text-xs text-muted-foreground/40">
				{tabs.find(t => t.path === activeTab)?.path || ''}
			</span>
		{/if}
	</div>

	<!-- Editor -->
	<div bind:this={editorContainer} class="flex-1"></div>
</div>

<style>
	:global(.chorus-dark .monaco-editor) {
		padding-top: 0;
	}
</style>
