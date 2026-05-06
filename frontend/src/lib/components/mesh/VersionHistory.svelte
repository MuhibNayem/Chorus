<script lang="ts">
	import { cn } from '$lib/utils';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import {
		X,
		History,
		Clock,
		Loader2,
		RotateCcw,
		Eye,
		ChevronDown,
		Bookmark,
		BookmarkCheck,
		FileCode,
		Database,
		Users,
		Folder,
		File,
		FolderOpen,
		ChevronRight
	} from 'lucide-svelte';

	let {
		projectId,
		onClose,
		onRestore
	}: {
		projectId: string;
		onClose: () => void;
		onRestore: (checkpointId: string) => void;
	} = $props();

	let checkpoints = $state<any[]>([]);
	let loading = $state(true);
	let loadingCheckpointId = $state<string | null>(null);
	let previewCheckpointId = $state<string | null>(null);
	let bookmarkedIds = $state<Set<string>>(new Set());

	let checkpointFiles = $state<any[]>([]);
	let loadingFiles = $state(false);
	let selectedFile = $state<{path: string; content: string; language: string} | null>(null);
	let expandedDirs = $state<Set<string>>(new Set());

	async function loadCheckpoints() {
		loading = true;
		try {
			const res = await fetch(`/api/projects/${projectId}/checkpoints?limit=50`);
			if (res.ok) {
				const data = await res.json();
				checkpoints = data.checkpoints || [];
			}
		} catch (e) {
			console.error('Failed to load checkpoints:', e);
		} finally {
			loading = false;
		}
	}

	async function loadCheckpointFiles(checkpointId: string) {
		loadingFiles = true;
		checkpointFiles = [];
		selectedFile = null;
		try {
			const res = await fetch(`/api/checkpoints/${projectId}/${checkpointId}/files`);
			if (res.ok) {
				const data = await res.json();
				checkpointFiles = data.files || [];
			}
		} catch (e) {
			console.error('Failed to load checkpoint files:', e);
		} finally {
			loadingFiles = false;
		}
	}

	async function selectFile(path: string) {
		try {
			const res = await fetch(`/api/checkpoints/${projectId}/${previewCheckpointId}/read?path=${encodeURIComponent(path)}`);
			if (res.ok) {
				const data = await res.json();
				selectedFile = {
					path: data.path,
					content: data.content,
					language: data.language || 'plaintext'
				};
			}
		} catch (e) {
			console.error('Failed to load file:', e);
		}
	}

	async function restoreCheckpoint(checkpointId: string) {
		if (loadingCheckpointId) return;
		loadingCheckpointId = checkpointId;
		try {
			const res = await fetch(`/api/projects/${projectId}/restore/${checkpointId}`, {
				method: 'POST'
			});
			if (res.ok) {
				onRestore(checkpointId);
			} else {
				const data = await res.json();
				alert(`Restore failed: ${data.error}`);
			}
		} catch (e) {
			console.error('Restore error:', e);
			alert('Restore failed. Check console for details.');
		} finally {
			loadingCheckpointId = null;
		}
	}

	function toggleBookmark(checkpointId: string) {
		if (bookmarkedIds.has(checkpointId)) {
			bookmarkedIds.delete(checkpointId);
		} else {
			bookmarkedIds.add(checkpointId);
		}
		bookmarkedIds = new Set(bookmarkedIds);
	}

	function toggleDir(path: string) {
		if (expandedDirs.has(path)) {
			expandedDirs.delete(path);
		} else {
			expandedDirs.add(path);
		}
		expandedDirs = new Set(expandedDirs);
	}

	function getFileIcon(file: any): typeof File {
		return File;
	}

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
			'sh': 'shell'
		};
		return langMap[ext] || 'plaintext';
	}

	function getPhaseColor(phase: string): string {
		switch (phase) {
			case 'before':
				return 'bg-amber-500/10 border-amber-500/30 text-amber-400';
			case 'after':
				return 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400';
			default:
				return 'bg-muted/30 border-border/40 text-muted-foreground';
		}
	}

	function formatDate(dateStr: string): string {
		const date = new Date(dateStr);
		const now = new Date();
		const diffMs = now.getTime() - date.getTime();
		const diffMins = Math.floor(diffMs / 60000);
		const diffHours = Math.floor(diffMs / 3600000);
		const diffDays = Math.floor(diffMs / 86400000);

		if (diffMins < 1) return 'Just now';
		if (diffMins < 60) return `${diffMins}m ago`;
		if (diffHours < 24) return `${diffHours}h ago`;
		if (diffDays < 7) return `${diffDays}d ago`;
		return date.toLocaleDateString();
	}

	$effect(() => {
		if (projectId) {
			loadCheckpoints();
		}
	});

	$effect(() => {
		if (previewCheckpointId) {
			loadCheckpointFiles(previewCheckpointId);
		} else {
			checkpointFiles = [];
			selectedFile = null;
		}
	});
</script>

<div class="flex h-full min-h-0 flex-col overflow-hidden rounded-[2rem] border border-white/55 bg-[linear-gradient(145deg,rgba(255,255,255,0.72),rgba(248,250,252,0.55))] shadow-[0_20px_54px_rgba(15,23,42,0.12)] backdrop-blur-2xl">
	<div class="flex items-center justify-between border-b border-white/40 px-5 py-4">
		<div class="flex items-center gap-3">
			<div class="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 border border-primary/20">
				<History class="h-5 w-5 text-primary" />
			</div>
			<div>
				<h2 class="text-sm font-bold tracking-tight">Version History</h2>
				<p class="text-[10px] text-muted-foreground/60">{checkpoints.length} checkpoints</p>
			</div>
		</div>
		<button
			type="button"
			class="rounded-lg p-2 text-muted-foreground/60 hover:bg-muted hover:text-foreground transition-colors"
			onclick={onClose}
		>
			<X class="h-4 w-4" />
		</button>
	</div>

	<ScrollArea class="min-h-0 flex-1">
		<div class="min-h-0 p-5 space-y-4">
			{#if loading}
				<div class="flex flex-col items-center justify-center py-16">
					<Loader2 class="h-8 w-8 animate-spin text-muted-foreground/40 mb-3" />
					<p class="text-sm text-muted-foreground/60">Loading checkpoints...</p>
				</div>
			{:else if checkpoints.length === 0}
				<div class="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
					<History class="h-8 w-8 mb-3 opacity-40" />
					<p class="text-sm">No checkpoints yet</p>
					<p class="text-xs mt-1">Checkpoints are created automatically during runs</p>
				</div>
			{:else}
				{#each checkpoints as checkpoint (checkpoint.id)}
					{@const metadata = checkpoint.metadata || {}}
					{@const aiContext = metadata.ai_context || {}}
					{@const isBookmarked = bookmarkedIds.has(checkpoint.id)}
					{@const isPreview = previewCheckpointId === checkpoint.id}
					{@const isRestoring = loadingCheckpointId === checkpoint.id}

					<div class={cn(
						"group relative overflow-hidden rounded-2xl border transition-all duration-300",
						isPreview
							? "border-white/55 bg-[linear-gradient(145deg,rgba(255,255,255,0.84),rgba(239,246,255,0.74))] shadow-[0_18px_40px_rgba(59,130,246,0.16)] ring-1 ring-cyan-300/30 scale-[1.01]"
							: "border-white/40 bg-white/30 shadow-[0_10px_24px_rgba(15,23,42,0.05)] hover:border-cyan-200/50 hover:bg-white/42 hover:shadow-[0_18px_44px_rgba(56,189,248,0.18)] hover:ring-1 hover:ring-cyan-300/35"
					)}>
						{#if !isPreview}
							<div class="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(56,189,248,0.18),transparent_62%)] opacity-0 transition-opacity duration-300 group-hover:opacity-100"></div>
							<div class="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 blur-[1px] opacity-0 transition-opacity duration-300 group-hover:opacity-100"></div>
						{/if}
						{#if isPreview}
							<div class="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-cyan-400 via-sky-500 to-teal-400"></div>
							<div class="absolute inset-x-0 top-0 h-px bg-white/80"></div>
						{/if}
						<div class="relative z-10 p-4">
							<div class="flex items-start justify-between gap-3">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2 flex-wrap">
										<h3 class={cn("text-sm font-semibold truncate transition-colors", isPreview ? "text-slate-900" : "text-slate-800")}>{checkpoint.label}</h3>
										<Badge variant="outline" class={cn("text-[10px] px-1.5 py-0 h-5", getPhaseColor(metadata.phase))}>
											{metadata.phase || 'checkpoint'}
										</Badge>
									</div>
									{#if checkpoint.trigger_message}
										<p class={cn("text-xs mt-1 line-clamp-2 italic transition-colors", isPreview ? "text-slate-700/80" : "text-muted-foreground/70")}>
											"{checkpoint.trigger_message}"
										</p>
									{/if}
									<div class={cn("mt-2 flex items-center gap-3 text-[10px] transition-colors", isPreview ? "text-slate-600/75" : "text-muted-foreground/50")}>
										<span class="flex items-center gap-1">
											<Clock class="h-3 w-3" />
											{formatDate(checkpoint.created_at)}
										</span>
										<span class="flex items-center gap-1">
											<FileCode class="h-3 w-3" />
											{metadata.file_count || 0} files
										</span>
										{#if aiContext.agent_summaries?.length > 0}
											<span class="flex items-center gap-1">
												<Users class="h-3 w-3" />
												{aiContext.agent_summaries.length} agents
											</span>
										{/if}
									</div>
								</div>

								<div class="flex items-center gap-1 shrink-0">
									<button
										type="button"
										class={cn(
											"rounded-lg p-2 transition-all",
											isPreview ? "text-primary/75 bg-white/55 shadow-sm ring-1 ring-white/60 hover:bg-white/75 hover:text-primary hover:ring-cyan-200/40" : "text-muted-foreground/50 hover:bg-muted hover:text-foreground"
										)}
										onclick={() => toggleBookmark(checkpoint.id)}
										title={isBookmarked ? 'Remove bookmark' : 'Bookmark'}
									>
										{#if isBookmarked}
											<BookmarkCheck class="h-4 w-4 text-primary" />
										{:else}
											<Bookmark class="h-4 w-4" />
										{/if}
									</button>
									<button
										type="button"
										class={cn(
											"rounded-lg p-2 transition-all",
											isPreview ? "text-primary/75 bg-white/55 shadow-sm ring-1 ring-white/60 hover:bg-white/75 hover:text-primary hover:ring-cyan-200/40" : "text-muted-foreground/50 hover:bg-muted hover:text-foreground"
										)}
										onclick={() => previewCheckpointId = isPreview ? null : checkpoint.id}
										title="Preview checkpoint files"
									>
										<Eye class="h-4 w-4" />
									</button>
								</div>
							</div>

							{#if aiContext.agent_summaries?.length > 0}
								<div class="mt-3 flex flex-wrap gap-1">
									{#each aiContext.agent_summaries.slice(0, 5) as agent}
										<Badge variant="secondary" class="text-[10px] px-1.5 py-0 h-5">
											{agent.agent_name}
										</Badge>
									{/each}
								</div>
							{/if}

							<div class="mt-3 flex items-center gap-2">
								<Button
									variant="outline"
									size="sm"
									class="h-8 text-xs rounded-lg"
									onclick={() => restoreCheckpoint(checkpoint.id)}
									disabled={isRestoring}
								>
									{#if isRestoring}
										<Loader2 class="h-3 w-3 mr-1 animate-spin" />
										Restoring...
									{:else}
										<RotateCcw class="h-3 w-3 mr-1" />
										Restore
									{/if}
								</Button>
							</div>
						</div>

						{#if isPreview}
							<div class="border-t border-white/20 bg-white/20 p-4 space-y-4">
								<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground/60 uppercase tracking-widest">
									<Database class="h-3 w-3" />
									Checkpoint Preview
								</div>

								{#if loadingFiles}
									<div class="flex items-center justify-center py-8">
										<Loader2 class="h-6 w-6 animate-spin text-muted-foreground/40" />
										<span class="ml-2 text-xs text-muted-foreground/60">Loading files...</span>
									</div>
								{:else if checkpointFiles.length > 0}
									<div class="grid min-h-0 grid-cols-2 gap-3">
										<div class="min-h-0 rounded-lg border border-white/20 bg-white/20 overflow-hidden">
											<div class="px-2 py-1.5 border-b border-white/10 bg-white/10">
												<span class="text-[10px] font-medium text-muted-foreground/60">Files ({checkpointFiles.length})</span>
											</div>
											<div class="max-h-56 overflow-y-auto p-1">
												{#each checkpointFiles.slice(0, 30) as file}
													<button
														type="button"
														class={cn(
															"w-full flex items-center gap-1.5 px-2 py-1 text-[11px] rounded hover:bg-white/10 transition-colors text-left",
															selectedFile?.path === file.path ? "bg-primary/10 text-primary" : "text-foreground/80"
														)}
														onclick={() => selectFile(file.path)}
													>
														<File class="h-3 w-3 text-blue-400/60 shrink-0" />
														<span class="truncate">{file.name}</span>
													</button>
												{/each}
												{#if checkpointFiles.length > 30}
													<p class="px-2 py-1 text-[10px] text-muted-foreground/50">
														+ {checkpointFiles.length - 30} more files
													</p>
												{/if}
											</div>
										</div>

										<div class="min-h-0 rounded-lg border border-white/20 bg-white/20 overflow-hidden">
											<div class="px-2 py-1.5 border-b border-white/10 bg-white/10">
												<span class="text-[10px] font-medium text-muted-foreground/60">
													{selectedFile ? selectedFile.path.split('/').pop() : 'Select a file'}
												</span>
											</div>
											<div class="max-h-56 overflow-y-auto p-2">
												{#if selectedFile}
													<pre class="text-[10px] text-foreground/70 whitespace-pre-wrap break-all font-mono">{selectedFile.content.slice(0, 1000)}{selectedFile.content.length > 1000 ? '\n\n... (truncated)' : ''}</pre>
												{:else}
													<p class="text-[10px] text-muted-foreground/50 text-center py-4">Click a file to preview</p>
												{/if}
											</div>
										</div>
									</div>
								{:else}
									<p class="text-xs text-muted-foreground/50 text-center py-4">No files in checkpoint</p>
								{/if}

								{#if aiContext.conversation_history?.length > 0}
									<div>
										<p class="text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-wider mb-2">Conversation Summary</p>
										<div class="space-y-1.5">
											{#each aiContext.conversation_history.slice(0, 4) as msg}
												<div class="flex items-start gap-2 text-xs">
													<span class={cn(
														"shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium",
														msg.role === 'user' ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
													)}>
														{msg.role}
													</span>
													<span class="text-muted-foreground/70 line-clamp-1">{msg.content}</span>
												</div>
											{/each}
											{#if aiContext.conversation_history.length > 4}
												<p class="text-[10px] text-muted-foreground/50 italic">
													+ {aiContext.conversation_history.length - 4} more messages
												</p>
											{/if}
										</div>
									</div>
								{/if}

								{#if aiContext.agent_summaries?.length > 0}
									<div>
										<p class="text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-wider mb-2">Agent Memory</p>
										<div class="space-y-2">
											{#each aiContext.agent_summaries as agent}
												<div class="rounded-lg bg-white/30 p-2.5 border border-white/20">
													<div class="flex items-center justify-between mb-1">
														<span class="text-xs font-semibold text-foreground/80">{agent.agent_name}</span>
														<span class="text-[10px] text-muted-foreground/50">{agent.source_event_count || 0} events</span>
													</div>
													{#if agent.summary}
														<p class="text-[11px] text-muted-foreground/70 line-clamp-2">{agent.summary}</p>
													{/if}
												</div>
											{/each}
										</div>
									</div>
								{/if}

								{#if metadata.size_bytes}
									<div class="text-[10px] text-muted-foreground/50">
										Size: {(metadata.size_bytes / 1024).toFixed(1)} KB
										{#if metadata.file_count} • {metadata.file_count} files{/if}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	</ScrollArea>

	{#if bookmarkedIds.size > 0}
		<div class="border-t border-white/20 p-3 bg-white/20">
			<div class="flex items-center justify-between text-xs text-muted-foreground/60">
				<span>{bookmarkedIds.size} bookmarked</span>
				<button
					type="button"
					class="text-primary hover:underline"
					onclick={() => bookmarkedIds = new Set()}
				>
					Clear all
				</button>
			</div>
		</div>
	{/if}
</div>
