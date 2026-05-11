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
			'java': 'java', 'svelte': 'html', 'ts': 'typescript', 'js': 'javascript',
			'json': 'json', 'yml': 'yaml', 'yaml': 'yaml', 'xml': 'xml',
			'properties': 'properties', 'gradle': 'groovy', 'md': 'markdown',
			'css': 'css', 'html': 'html', 'txt': 'plaintext', 'py': 'python',
			'sh': 'shell', 'bash': 'shell'
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
				'editorCursor.foreground': '#58a6ff',
				'editorLineNumber.foreground': '#484f58',
				'editorLineNumber.activeForeground': '#c9d1d9',
				'editorWidget.background': '#161b22',
				'editorWidget.border': '#30363d',
			}
		});

		editor = monaco.editor.create(editorContainer, {
			value: currentContent,
			language: 'plaintext',
			theme: 'chorus-dark',
			readOnly: readOnly,
			minimap: { enabled: false },
			fontSize: 12.5,
			fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
			lineNumbers: 'on',
			scrollBeyondLastLine: false,
			renderLineHighlight: 'line',
			padding: { top: 12, bottom: 12 },
			automaticLayout: true,
			tabSize: 4,
			wordWrap: 'on',
			scrollbar: {
				verticalScrollbarSize: 6,
				horizontalScrollbarSize: 6,
				useShadows: false
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

<div class="editor-wrap">
	<!-- Tabs -->
	{#if tabs.length > 0}
		<div class="tab-bar">
			{#each tabs as tab (tab.path)}
				<button
					type="button"
					class="tab {activeTab === tab.path ? 'active' : ''}"
					onclick={() => {
						onTabSelect?.(tab.path);
						loadTab(tab);
					}}
					role="tab"
					aria-selected={activeTab === tab.path}
				>
					<span class="tab-name">{tab.name}</span>
					{#if onTabClose}
						<span
							onclick={(e) => { e.stopPropagation(); onTabClose?.(tab.path); }}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onTabClose?.(tab.path); }}}
							class="tab-close"
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
	<div class="toolbar">
		<button onclick={copyContent} class="tool-btn" title="Copy content">
			{#if copied}
				<Check class="h-3.5 w-3.5" style="color: oklch(75% 0.14 150);" />
				<span>Copied!</span>
			{:else}
				<Copy class="h-3.5 w-3.5" />
				<span>Copy</span>
			{/if}
		</button>
		<button onclick={downloadFile} class="tool-btn" title="Download file">
			<Download class="h-3.5 w-3.5" />
			<span>Download</span>
		</button>
		<button onclick={downloadProjectZip} disabled={!projectId} class="tool-btn" title="Project ZIP">
			<FolderArchive class="h-3.5 w-3.5" />
			<span>ZIP</span>
		</button>
		<div class="flex-1"></div>
		{#if activeTab}
			<span class="file-path">{tabs.find(t => t.path === activeTab)?.path || ''}</span>
		{/if}
	</div>

	<!-- Editor -->
	<div bind:this={editorContainer} class="editor-area"></div>
</div>

<style>
	.editor-wrap {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--ink-0);
	}

	.tab-bar {
		display: flex;
		align-items: center;
		background: var(--ink-0);
		border-bottom: 1px solid rgba(255,255,255,0.06);
		overflow-x: auto;
		flex-shrink: 0;
	}
	.tab-bar::-webkit-scrollbar { height: 0; }

	.tab {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		font-size: 11.5px;
		font-family: var(--font-mono);
		border: none;
		border-right: 1px solid rgba(255,255,255,0.05);
		background: transparent;
		color: rgba(255,255,255,0.40);
		cursor: pointer;
		white-space: nowrap;
		transition: color 120ms ease, background 120ms ease;
	}
	.tab:hover {
		color: rgba(255,255,255,0.70);
		background: rgba(255,255,255,0.03);
	}
	.tab.active {
		color: rgba(255,255,255,0.90);
		background: rgba(255,255,255,0.04);
	}

	.tab-name {
		max-width: 140px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.tab-close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 2px;
		border-radius: 4px;
		opacity: 0;
		transition: opacity 120ms ease, background 120ms ease;
		line-height: 0;
	}
	.tab:hover .tab-close {
		opacity: 1;
	}
	.tab-close:hover {
		background: rgba(255,255,255,0.10);
	}

	.toolbar {
		display: flex;
		align-items: center;
		gap: 2px;
		padding: 4px 10px;
		border-bottom: 1px solid rgba(255,255,255,0.04);
		background: var(--ink-0);
		flex-shrink: 0;
	}

	.tool-btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 8px;
		font-size: 11px;
		font-family: var(--font-mono);
		color: rgba(255,255,255,0.40);
		background: none;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		transition: color 120ms ease, background 120ms ease;
		line-height: 1;
	}
	.tool-btn:hover {
		color: rgba(255,255,255,0.75);
		background: rgba(255,255,255,0.05);
	}
	.tool-btn:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}

	.file-path {
		font-size: 10.5px;
		font-family: var(--font-mono);
		color: rgba(255,255,255,0.25);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 50%;
	}

	.editor-area {
		flex: 1;
		min-height: 0;
	}
</style>
