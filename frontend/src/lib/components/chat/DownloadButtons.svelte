<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Card, CardContent } from '$lib/components/ui/card';
	import { FileArchive, Play, CheckCircle2, AlertTriangle, RefreshCw, Download } from 'lucide-svelte';

	let {
		projectName = 'project',
		projectId = '',
		zipUrl = '',
		dockerUrl = ''
	}: { projectName?: string; projectId?: string; zipUrl?: string; dockerUrl?: string } = $props();

	let isDownloading = $state(false);
	let downloadError = $state('');
	let isRegenerating = $state(false);
	let currentZipUrl = $state(zipUrl);
	let currentDockerUrl = $state(dockerUrl);

	async function downloadZip() {
		if (!currentZipUrl) return;
		isDownloading = true;
		downloadError = '';

		try {
			const response = await fetch(currentZipUrl);
			if (!response.ok) {
				const err = await response.json().catch(() => ({ error: 'Download failed' }));
				throw new Error(err.error || `HTTP ${response.status}`);
			}

			const blob = await response.blob();
			const url = window.URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `project_${projectName}.zip`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			window.URL.revokeObjectURL(url);
		} catch (err: any) {
			downloadError = err.message || 'Download failed. The link may have expired.';
		} finally {
			isDownloading = false;
		}
	}

	async function regenerateUrl() {
		if (!projectId) return;
		isRegenerating = true;
		downloadError = '';

		try {
			const response = await fetch(`/api/download/${projectId}/url`);
			if (!response.ok) {
				const err = await response.json().catch(() => ({ error: 'Failed to regenerate' }));
				throw new Error(err.error || `HTTP ${response.status}`);
			}
			const data = await response.json();
			if (data.zip_url) {
				currentZipUrl = data.zip_url;
			}
			if (data.download_url) {
				currentDockerUrl = data.download_url;
			}
		} catch (err: any) {
			downloadError = err.message || 'Failed to regenerate download link.';
		} finally {
			isRegenerating = false;
		}
	}

	function openDockerUrl() {
		if (currentDockerUrl) {
			window.open(currentDockerUrl, '_blank');
		}
	}
</script>

<Card class="rounded-3xl border-emerald-200 bg-gradient-to-br from-emerald-50/80 to-white/80 backdrop-blur-xl shadow-[0_0_20px_rgba(16,185,129,0.15)] overflow-hidden">
	<CardContent class="p-6 space-y-4">
		<div class="flex items-center gap-3">
			<div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-200 text-emerald-700 shadow-sm">
				<CheckCircle2 class="h-6 w-6" />
			</div>
			<div>
				<h3 class="text-base font-bold tracking-tight text-emerald-900">Project Ready!</h3>
				<p class="text-sm text-emerald-700/70">{projectName} has been generated successfully</p>
			</div>
		</div>

		<div class="flex gap-3">
			<Button
				onclick={downloadZip}
				disabled={isDownloading || !currentZipUrl}
				class="flex-1 h-12 rounded-2xl bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg shadow-emerald-200 transition-all hover:scale-[1.02] disabled:opacity-60"
			>
				{#if isDownloading}
					<RefreshCw class="mr-2 h-5 w-5 animate-spin" />
					Downloading...
				{:else}
					<Download class="mr-2 h-5 w-5" />
					Download ZIP
				{/if}
			</Button>
			<Button
				variant="outline"
				onclick={openDockerUrl}
				disabled={!currentDockerUrl}
				class="flex-1 h-12 rounded-2xl border-emerald-300 text-emerald-700 hover:bg-emerald-50 transition-all hover:scale-[1.02] disabled:opacity-60"
			>
				<Play class="mr-2 h-5 w-5" />
				Run with Docker
			</Button>
		</div>

		{#if downloadError}
			<div class="flex items-start gap-2 rounded-xl bg-rose-50 border border-rose-200 px-3 py-2.5">
				<AlertTriangle class="h-4 w-4 shrink-0 text-rose-500 mt-0.5" />
				<div class="min-w-0 flex-1">
					<p class="text-xs text-rose-700 font-medium">{downloadError}</p>
					{#if projectId}
						<button
							onclick={regenerateUrl}
							disabled={isRegenerating}
							class="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600 hover:text-emerald-700 transition-colors disabled:opacity-50"
						>
							<RefreshCw class="h-3 w-3 {isRegenerating ? 'animate-spin' : ''}" />
							{isRegenerating ? 'Regenerating...' : 'Regenerate download link'}
						</button>
					{/if}
				</div>
			</div>
		{/if}
	</CardContent>
</Card>
