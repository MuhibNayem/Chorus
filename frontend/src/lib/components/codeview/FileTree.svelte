<script lang="ts">
	import {
		Folder,
		FolderOpen,
		Coffee,
		Image,
		Braces,
		CodeXml,
		ScrollText,
		FileCog,
		FileCode,
		FileText,
		FileTerminal,
		FileType,
		ChevronRight,
		ChevronDown,
		Search,
		X
	} from 'lucide-svelte';

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

	interface FileVisual {
		icon: typeof FileCode;
		tone: string;
		accent: string;
	}

	const EXACT_FILE_VISUALS: Record<string, FileVisual> = {
		'pom.xml': { icon: Coffee, tone: 'text-red-500/90', accent: 'bg-red-500/10 ring-red-500/15' },
		'build.gradle': { icon: Coffee, tone: 'text-red-500/90', accent: 'bg-red-500/10 ring-red-500/15' },
		'build.gradle.kts': { icon: Coffee, tone: 'text-red-500/90', accent: 'bg-red-500/10 ring-red-500/15' },
		'gradlew': { icon: Coffee, tone: 'text-red-500/90', accent: 'bg-red-500/10 ring-red-500/15' },
		'dockerfile': { icon: FileTerminal, tone: 'text-orange-500/85', accent: 'bg-orange-500/10 ring-orange-500/15' },
		'readme.md': { icon: FileText, tone: 'text-sky-500/85', accent: 'bg-sky-500/10 ring-sky-500/15' },
		'changelog.md': { icon: ScrollText, tone: 'text-sky-500/85', accent: 'bg-sky-500/10 ring-sky-500/15' },
		'package.json': { icon: FileCode, tone: 'text-amber-500/90', accent: 'bg-amber-500/10 ring-amber-500/15' },
		'pnpm-lock.yaml': { icon: FileType, tone: 'text-violet-500/85', accent: 'bg-violet-500/10 ring-violet-500/15' },
		'package-lock.json': { icon: FileType, tone: 'text-violet-500/85', accent: 'bg-violet-500/10 ring-violet-500/15' },
		'yarn.lock': { icon: FileType, tone: 'text-violet-500/85', accent: 'bg-violet-500/10 ring-violet-500/15' },
		'tsconfig.json': { icon: FileType, tone: 'text-blue-500/85', accent: 'bg-blue-500/10 ring-blue-500/15' },
		'jsconfig.json': { icon: FileType, tone: 'text-blue-500/85', accent: 'bg-blue-500/10 ring-blue-500/15' },
		'vite.config.ts': { icon: FileCode, tone: 'text-cyan-500/85', accent: 'bg-cyan-500/10 ring-cyan-500/15' },
		'svelte.config.js': { icon: FileCode, tone: 'text-orange-500/85', accent: 'bg-orange-500/10 ring-orange-500/15' },
		'tailwind.config.js': { icon: FileCode, tone: 'text-cyan-500/85', accent: 'bg-cyan-500/10 ring-cyan-500/15' },
		'prettier.config.js': { icon: FileCode, tone: 'text-pink-500/85', accent: 'bg-pink-500/10 ring-pink-500/15' },
		'eslint.config.js': { icon: FileCode, tone: 'text-emerald-500/85', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'postcss.config.js': { icon: FileCode, tone: 'text-fuchsia-500/85', accent: 'bg-fuchsia-500/10 ring-fuchsia-500/15' },
		'favicon.svg': { icon: CodeXml, tone: 'text-cyan-500/90', accent: 'bg-cyan-500/10 ring-cyan-500/15' },
		'favicon.png': { icon: Image, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'.env': { icon: FileCog, tone: 'text-amber-500/90', accent: 'bg-amber-500/10 ring-amber-500/15' }
	};

	const EXTENSION_VISUALS: Record<string, FileVisual> = {
		'js': { icon: FileCode, tone: 'text-yellow-500/90', accent: 'bg-yellow-500/10 ring-yellow-500/15' },
		'mjs': { icon: FileCode, tone: 'text-yellow-500/90', accent: 'bg-yellow-500/10 ring-yellow-500/15' },
		'cjs': { icon: FileCode, tone: 'text-yellow-500/90', accent: 'bg-yellow-500/10 ring-yellow-500/15' },
		'ts': { icon: FileCode, tone: 'text-sky-500/90', accent: 'bg-sky-500/10 ring-sky-500/15' },
		'tsx': { icon: FileCode, tone: 'text-sky-500/90', accent: 'bg-sky-500/10 ring-sky-500/15' },
		'jsx': { icon: FileCode, tone: 'text-amber-500/90', accent: 'bg-amber-500/10 ring-amber-500/15' },
		'json': { icon: FileCode, tone: 'text-zinc-500/90', accent: 'bg-zinc-500/10 ring-zinc-500/15' },
		'yaml': { icon: FileType, tone: 'text-rose-500/90', accent: 'bg-rose-500/10 ring-rose-500/15' },
		'yml': { icon: FileType, tone: 'text-rose-500/90', accent: 'bg-rose-500/10 ring-rose-500/15' },
		'html': { icon: FileType, tone: 'text-orange-500/90', accent: 'bg-orange-500/10 ring-orange-500/15' },
		'css': { icon: FileType, tone: 'text-cyan-500/90', accent: 'bg-cyan-500/10 ring-cyan-500/15' },
		'scss': { icon: FileType, tone: 'text-pink-500/90', accent: 'bg-pink-500/10 ring-pink-500/15' },
		'md': { icon: FileText, tone: 'text-sky-500/90', accent: 'bg-sky-500/10 ring-sky-500/15' },
		'txt': { icon: FileText, tone: 'text-slate-500/90', accent: 'bg-slate-500/10 ring-slate-500/15' },
		'java': { icon: Coffee, tone: 'text-red-500/90', accent: 'bg-red-500/10 ring-red-500/15' },
		'kt': { icon: FileCode, tone: 'text-violet-500/90', accent: 'bg-violet-500/10 ring-violet-500/15' },
		'kts': { icon: FileCode, tone: 'text-violet-500/90', accent: 'bg-violet-500/10 ring-violet-500/15' },
		'py': { icon: FileCode, tone: 'text-blue-500/90', accent: 'bg-blue-500/10 ring-blue-500/15' },
		'sh': { icon: FileTerminal, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'bash': { icon: FileTerminal, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'png': { icon: Image, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'jpg': { icon: Image, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'jpeg': { icon: Image, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'gif': { icon: Image, tone: 'text-emerald-500/90', accent: 'bg-emerald-500/10 ring-emerald-500/15' },
		'svg': { icon: CodeXml, tone: 'text-cyan-500/90', accent: 'bg-cyan-500/10 ring-cyan-500/15' },
		'pdf': { icon: FileText, tone: 'text-rose-500/90', accent: 'bg-rose-500/10 ring-rose-500/15' },
		'log': { icon: ScrollText, tone: 'text-slate-500/90', accent: 'bg-slate-500/10 ring-slate-500/15' },
		'xml': { icon: CodeXml, tone: 'text-orange-500/90', accent: 'bg-orange-500/10 ring-orange-500/15' }
	};

	function toggleDir(path: string) {
		if (expandedDirs.has(path)) {
			expandedDirs.delete(path);
		} else {
			expandedDirs.add(path);
		}
		expandedDirs = new Set(expandedDirs);
	}

	function getFileIcon(node: FileNode) {
		if (node.type === 'directory') {
			return expandedDirs.has(node.path) ? FolderOpen : Folder;
		}
		return getFileVisual(node).icon;
	}

	function getFileVisual(node: FileNode): FileVisual {
		const lowerName = node.name.toLowerCase();
		const exactMatch = EXACT_FILE_VISUALS[lowerName];
		if (exactMatch) return exactMatch;

		const parts = lowerName.split('.');
		const extension = parts.length > 1 ? parts.pop() || '' : '';
		return EXTENSION_VISUALS[extension] || { icon: FileText, tone: 'text-muted-foreground/70', accent: 'bg-white/40 ring-white/30' };
	}

	function filterFiles(nodes: FileNode[], query: string): FileNode[] {
		if (!query) return nodes;
		const lower = query.toLowerCase();
		return nodes.reduce<FileNode[]>((acc, node) => {
			if (node.name.toLowerCase().includes(lower)) {
				acc.push(node);
			} else if (node.type === 'directory' && node.children) {
				const filtered = filterFiles(node.children, query);
				if (filtered.length > 0) {
					acc.push({ ...node, children: filtered });
				}
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

<div class="flex flex-col h-full bg-white/20">
	<div class="px-4 py-4 border-b border-white/40">
		<div class="mb-3 flex items-start justify-between gap-2">
			<div>
				<p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/55">Folder Layout</p>
				<p class="mt-1 text-xs text-muted-foreground/60">Open folders to explore the workspace structure.</p>
			</div>
		</div>
		<div class="relative">
			<Search class="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/45" />
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Search files..."
				class="w-full h-9 rounded-xl border border-white/40 bg-white/60 pl-9 pr-8 text-xs shadow-sm outline-none transition-colors placeholder:text-muted-foreground/35 focus:border-primary/30 focus:bg-white"
			/>
			{#if searchQuery}
				<button
					type="button"
					onclick={() => searchQuery = ''}
					class="absolute right-2.5 top-1/2 -translate-y-1/2"
				>
					<X class="h-3.5 w-3.5 text-muted-foreground/50 hover:text-muted-foreground" />
				</button>
			{/if}
		</div>
	</div>

	<div class="flex-1 overflow-auto px-2 py-3">
		{#each visibleNodes as { node, depth, isExpanded } (node.path)}
			{@const Icon = getFileIcon(node)}
			{@const visual = getFileVisual(node)}
			{@const isDir = node.type === 'directory'}
			{@const isSelected = selectedPath === node.path}
			{@const hasChildren = Boolean(node.children && node.children.length > 0)}

				<div
					role="treeitem"
					tabindex="-1"
					aria-selected={isSelected}
					class="tree-node min-w-max"
					style="padding-left: {depth * 14}px"
				>
					<button
						type="button"
						class="inline-flex w-max min-w-max items-center gap-2 rounded-lg px-2 py-2 text-xs whitespace-nowrap transition-colors hover:bg-white/50 {isSelected ? 'bg-primary/10 text-primary ring-1 ring-primary/20' : 'text-foreground/78'}"
						onclick={() => isDir ? toggleDir(node.path) : onFileSelect(node.path)}
					>
					{#if isDir}
						<span class="w-4 flex items-center justify-center shrink-0">
							{#if isExpanded}
								<ChevronDown class="h-3 w-3 text-muted-foreground/50" />
							{:else}
								<ChevronRight class="h-3 w-3 text-muted-foreground/50" />
							{/if}
						</span>
					{:else if hasChildren}
						<span class="w-4"></span>
					{:else}
						<span class="w-4"></span>
					{/if}

					<span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md ring-1 {isDir ? 'bg-amber-500/10 ring-amber-500/15' : visual.accent}">
						<Icon class="h-3.5 w-3.5 {isDir ? 'text-amber-500/85' : visual.tone}"></Icon>
					</span>

					<span class="font-medium">{node.name}</span>
				</button>
			</div>
		{/each}

		{#if visibleNodes.length === 0}
			<div class="px-3 py-6 text-center text-xs text-muted-foreground/50">
				{searchQuery ? 'No files match your search' : 'No files in workspace'}
			</div>
		{/if}
	</div>
</div>
