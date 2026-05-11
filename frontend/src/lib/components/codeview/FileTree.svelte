<script lang="ts">
	import Folder from '@lucide/svelte/icons/folder';
	import FolderOpen from '@lucide/svelte/icons/folder-open';
	import Coffee from '@lucide/svelte/icons/coffee';
	import Image from '@lucide/svelte/icons/image';
	import Braces from '@lucide/svelte/icons/braces';
	import CodeXml from '@lucide/svelte/icons/code-xml';
	import ScrollText from '@lucide/svelte/icons/scroll-text';
	import FileCog from '@lucide/svelte/icons/file-cog';
	import FileCode from '@lucide/svelte/icons/file-code';
	import FileText from '@lucide/svelte/icons/file-text';
	import FileTerminal from '@lucide/svelte/icons/file-terminal';
	import FileType from '@lucide/svelte/icons/file-type';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Search from '@lucide/svelte/icons/search';
	import X from '@lucide/svelte/icons/x';

	interface FileNode {
		name: string;
		path: string;
		type: 'file' | 'directory';
		children?: FileNode[];
	}

	interface Props {
		files: FileNode[];
		onFileSelect: (path: string) => void;
		selectedPath?: string;
	}

	let { files, onFileSelect, selectedPath }: Props = $props();

	let expandedDirs = $state<Set<string>>(new Set());
	let searchQuery = $state('');

	interface VisibleNode {
		node: FileNode;
		depth: number;
		isExpanded: boolean;
	}

	function toggleDir(path: string) {
		if (expandedDirs.has(path)) {
			expandedDirs.delete(path);
		} else {
			expandedDirs.add(path);
		}
		expandedDirs = new Set(expandedDirs);
	}

	interface FileVisual {
		icon: typeof FileCode;
		tone: string;
		bg: string;
	}

	const EXACT_VISUALS: Record<string, FileVisual> = {
		'pom.xml': { icon: Coffee, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		'build.gradle': { icon: Coffee, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		'build.gradle.kts': { icon: Coffee, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		'gradlew': { icon: Coffee, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		'dockerfile': { icon: FileTerminal, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		'readme.md': { icon: FileText, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		'changelog.md': { icon: ScrollText, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		'package.json': { icon: Braces, tone: 'oklch(82% 0.10 75)', bg: 'oklch(82% 0.10 75 / 0.12)' },
		'pnpm-lock.yaml': { icon: FileType, tone: 'oklch(70% 0.16 295)', bg: 'oklch(70% 0.16 295 / 0.12)' },
		'package-lock.json': { icon: FileType, tone: 'oklch(70% 0.16 295)', bg: 'oklch(70% 0.16 295 / 0.12)' },
		'yarn.lock': { icon: FileType, tone: 'oklch(70% 0.16 295)', bg: 'oklch(70% 0.16 295 / 0.12)' },
		'tsconfig.json': { icon: FileCog, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		'vite.config.ts': { icon: FileCog, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		'svelte.config.js': { icon: FileCog, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		'tailwind.config.js': { icon: FileCog, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		'favicon.svg': { icon: CodeXml, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		'.env': { icon: FileCog, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' }
	};

	const EXTENSION_VISUALS: Record<string, FileVisual> = {
		js: { icon: FileCode, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		mjs: { icon: FileCode, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		cjs: { icon: FileCode, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		ts: { icon: FileCode, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		tsx: { icon: FileCode, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		jsx: { icon: FileCode, tone: 'oklch(82% 0.13 75)', bg: 'oklch(82% 0.13 75 / 0.12)' },
		json: { icon: Braces, tone: 'oklch(82% 0.10 75)', bg: 'oklch(82% 0.10 75 / 0.12)' },
		yaml: { icon: FileType, tone: 'oklch(74% 0.12 18)', bg: 'oklch(74% 0.12 18 / 0.12)' },
		yml: { icon: FileType, tone: 'oklch(74% 0.12 18)', bg: 'oklch(74% 0.12 18 / 0.12)' },
		html: { icon: CodeXml, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		css: { icon: FileType, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		scss: { icon: FileType, tone: 'oklch(78% 0.12 340)', bg: 'oklch(78% 0.12 340 / 0.12)' },
		md: { icon: FileText, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		txt: { icon: FileText, tone: 'oklch(80% 0.04 280)', bg: 'oklch(80% 0.04 280 / 0.12)' },
		java: { icon: Coffee, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		kt: { icon: FileCode, tone: 'oklch(70% 0.16 295)', bg: 'oklch(70% 0.16 295 / 0.12)' },
		py: { icon: FileCode, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		go: { icon: FileCode, tone: 'oklch(78% 0.13 220)', bg: 'oklch(78% 0.13 220 / 0.12)' },
		rs: { icon: FileCode, tone: 'oklch(70% 0.16 18)', bg: 'oklch(70% 0.16 18 / 0.12)' },
		sh: { icon: FileTerminal, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		bash: { icon: FileTerminal, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		svg: { icon: CodeXml, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		png: { icon: Image, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		jpg: { icon: Image, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		jpeg: { icon: Image, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		gif: { icon: Image, tone: 'oklch(75% 0.14 150)', bg: 'oklch(75% 0.14 150 / 0.12)' },
		xml: { icon: CodeXml, tone: 'oklch(80% 0.14 75)', bg: 'oklch(80% 0.14 75 / 0.12)' },
		log: { icon: ScrollText, tone: 'oklch(80% 0.04 280)', bg: 'oklch(80% 0.04 280 / 0.12)' }
	};

	function getFileVisual(node: FileNode): FileVisual {
		if (node.type === 'directory') {
			return {
				icon: expandedDirs.has(node.path) ? FolderOpen : Folder,
				tone: 'oklch(80% 0.14 75)',
				bg: 'oklch(80% 0.14 75 / 0.12)'
			};
		}
		const lower = node.name.toLowerCase();
		if (EXACT_VISUALS[lower]) return EXACT_VISUALS[lower];
		const ext = lower.split('.').pop() || '';
		return EXTENSION_VISUALS[ext] || {
			icon: FileText,
			tone: 'rgba(255,255,255,0.38)',
			bg: 'rgba(255,255,255,0.06)'
		};
	}

	function filterFiles(nodes: FileNode[], query: string): FileNode[] {
		if (!query) return nodes;
		const lower = query.toLowerCase();
		return nodes.reduce<FileNode[]>((acc, node) => {
			if (node.name.toLowerCase().includes(lower)) {
				acc.push(node);
			} else if (node.type === 'directory' && node.children) {
				const filtered = filterFiles(node.children, lower);
				if (filtered.length > 0) acc.push({ ...node, children: filtered });
			}
			return acc;
		}, []);
	}

	let filteredFiles = $derived(filterFiles(files, searchQuery));

	function buildVisibleNodes(nodes: FileNode[], depth = 0): VisibleNode[] {
		const rows: VisibleNode[] = [];
		for (const node of nodes) {
			const isExpanded = node.type === 'directory' && expandedDirs.has(node.path);
			rows.push({ node, depth, isExpanded });
			const shouldTraverse = node.type === 'directory' && node.children && node.children.length > 0;
			const shouldShowChildren = shouldTraverse && (searchQuery.length > 0 || isExpanded);
			if (shouldShowChildren && node.children) {
				rows.push(...buildVisibleNodes(node.children, depth + 1));
			}
		}
		return rows;
	}

	let visibleNodes = $derived(buildVisibleNodes(filteredFiles));
</script>

<div class="file-tree">
	<div class="tree-header">
		<p class="eyebrow">Explorer</p>
		<div class="search-wrap">
			<Search class="search-icon" />
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Search files..."
			/>
			{#if searchQuery}
				<button type="button" class="clear-btn" onclick={() => searchQuery = ''}>
					<X class="h-3 w-3" />
				</button>
			{/if}
		</div>
	</div>

	<div class="tree-scroll">
		{#each visibleNodes as { node, depth, isExpanded } (node.path)}
			{@const isDir = node.type === 'directory'}
			{@const isSelected = selectedPath === node.path}
			{@const visual = getFileVisual(node)}
			{@const Icon = visual.icon}

			<div class="tree-row" style="padding-left: {depth * 14 + 8}px">
				<button
					type="button"
					class="tree-node {isSelected ? 'active' : ''}"
					onclick={() => isDir ? toggleDir(node.path) : onFileSelect(node.path)}
				>
					{#if isDir}
						<span class="chevron">
							{#if isExpanded}
								<ChevronDown class="h-3 w-3" />
							{:else}
								<ChevronRight class="h-3 w-3" />
							{/if}
						</span>
					{:else}
						<span class="chevron-placeholder"></span>
					{/if}

					<span class="file-icon" style="background: {visual.bg}; color: {visual.tone};">
						<Icon class="h-3.5 w-3.5" />
					</span>
					<span class="label">{node.name}</span>
				</button>
			</div>
		{/each}

		{#if visibleNodes.length === 0}
			<div class="empty">{searchQuery ? 'No files match' : 'No files'}</div>
		{/if}
	</div>
</div>

<style>
	.file-tree {
		display: flex;
		flex-direction: column;
		height: 100%;
		font-family: var(--font-mono);
		font-size: 11.5px;
		color: rgba(255,255,255,0.55);
	}

	.tree-header {
		padding: 12px 12px 10px;
		border-bottom: 1px solid rgba(255,255,255,0.06);
		flex-shrink: 0;
	}

	.eyebrow {
		margin: 0 0 8px;
		font-size: 10px;
		font-weight: 500;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: rgba(255,255,255,0.40);
	}

	.search-wrap {
		position: relative;
	}
	.search-wrap :global(.search-icon) {
		position: absolute;
		left: 8px;
		top: 50%;
		transform: translateY(-50%);
		width: 12px;
		height: 12px;
		color: rgba(255,255,255,0.30);
		pointer-events: none;
	}
	.search-wrap input {
		width: 100%;
		height: 28px;
		border-radius: 7px;
		border: 1px solid rgba(255,255,255,0.08);
		background: rgba(255,255,255,0.04);
		padding: 0 22px 0 24px;
		font-family: inherit;
		font-size: 11px;
		color: rgba(255,255,255,0.70);
		outline: none;
		transition: border-color 150ms ease, background 150ms ease;
	}
	.search-wrap input::placeholder {
		color: rgba(255,255,255,0.25);
	}
	.search-wrap input:focus {
		border-color: rgba(167,139,250,0.35);
		background: rgba(255,255,255,0.06);
	}
	.clear-btn {
		position: absolute;
		right: 6px;
		top: 50%;
		transform: translateY(-50%);
		background: none;
		border: none;
		padding: 2px;
		color: rgba(255,255,255,0.35);
		cursor: pointer;
		line-height: 0;
	}
	.clear-btn:hover { color: rgba(255,255,255,0.60); }

	.tree-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 6px 6px 12px;
	}
	.tree-scroll::-webkit-scrollbar { width: 4px; }
	.tree-scroll::-webkit-scrollbar-thumb {
		background: rgba(255,255,255,0.08);
		border-radius: 4px;
	}

	.tree-row {
		display: flex;
		align-items: center;
	}

	.tree-node {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 3px 7px;
		border-radius: 6px;
		white-space: nowrap;
		cursor: pointer;
		background: none;
		border: none;
		font-family: inherit;
		font-size: inherit;
		color: inherit;
		width: 100%;
		text-align: left;
		transition: background 120ms ease;
	}
	.tree-node:hover {
		background: rgba(255,255,255,0.04);
	}
	.tree-node.active {
		background: rgba(167,139,250,0.10);
		color: white;
	}
	.tree-node.active .file-icon {
		box-shadow: 0 0 0 1px rgba(167,139,250,0.28), 0 0 10px rgba(167,139,250,0.16);
	}

	.chevron {
		width: 14px;
		height: 14px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		color: rgba(255,255,255,0.30);
	}
	.chevron-placeholder {
		width: 14px;
		flex-shrink: 0;
	}

	.file-icon {
		width: 20px;
		height: 20px;
		border-radius: 5px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		transition: box-shadow 150ms ease, color 150ms ease, background 150ms ease;
	}

	.label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.empty {
		padding: 24px 8px;
		text-align: center;
		color: rgba(255,255,255,0.25);
		font-size: 11px;
	}
</style>
