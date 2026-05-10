<script lang="ts">
	import { settings, type AppSettings, type ThemeMode, type AccentColor, type FontSize, type Density, type ContextMode } from '$lib/settings.svelte';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Palette from '@lucide/svelte/icons/palette';
	import MessageSquare from '@lucide/svelte/icons/message-square';
	import Shield from '@lucide/svelte/icons/shield';
	import Zap from '@lucide/svelte/icons/zap';
	import Check from '@lucide/svelte/icons/check';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import Monitor from '@lucide/svelte/icons/monitor';
	import Type from '@lucide/svelte/icons/type';
	import Layout from '@lucide/svelte/icons/layout';
	import Brain from '@lucide/svelte/icons/brain';
	import Terminal from '@lucide/svelte/icons/terminal';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';

	let currentTab = $state('appearance');
	let localSettings = $state<AppSettings>({ ...$settings });
	let showResetConfirm = $state(false);
	let showClearHistoryConfirm = $state(false);

	const tabs = [
		{ id: 'appearance', label: 'Appearance', icon: Palette },
		{ id: 'chat', label: 'Chat', icon: MessageSquare },
		{ id: 'privacy', label: 'Privacy', icon: Shield },
		{ id: 'advanced', label: 'Advanced', icon: Zap },
	];

	const themeOptions: { value: ThemeMode; label: string; icon: any }[] = [
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'system', label: 'System', icon: Monitor },
	];

	const accentOptions: { value: AccentColor; label: string; color: string }[] = [
		{ value: 'purple', label: 'Purple', color: 'bg-purple-500' },
		{ value: 'blue', label: 'Blue', color: 'bg-blue-500' },
		{ value: 'green', label: 'Green', color: 'bg-emerald-500' },
		{ value: 'orange', label: 'Orange', color: 'bg-orange-500' },
		{ value: 'rose', label: 'Rose', color: 'bg-rose-500' },
		{ value: 'slate', label: 'Slate', color: 'bg-slate-500' },
	];

	const fontSizeOptions: { value: FontSize; label: string }[] = [
		{ value: 'small', label: 'Small' },
		{ value: 'default', label: 'Default' },
		{ value: 'large', label: 'Large' },
	];

	const densityOptions: { value: Density; label: string }[] = [
		{ value: 'compact', label: 'Compact' },
		{ value: 'default', label: 'Default' },
		{ value: 'comfortable', label: 'Comfortable' },
	];

	const contextModeOptions: { value: ContextMode; label: string; desc: string }[] = [
		{ value: 'auto', label: 'Auto', desc: 'Automatically choose context depth' },
		{ value: 'lean', label: 'Lean', desc: 'Minimal context for faster responses' },
		{ value: 'full', label: 'Full', desc: 'Maximum context for complex tasks' },
	];

	function updateSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
		localSettings = { ...localSettings, [key]: value };
		settings.set({ ...localSettings });
	}

	function handleReset() {
		settings.reset();
		localSettings = { ...$settings };
		showResetConfirm = false;
	}

	function handleClearHistory() {
		localStorage.removeItem('chorus.activeProjectId');
		localStorage.removeItem('chorus.chatHistory');
		showClearHistoryConfirm = false;
	}
</script>

<div class="flex h-screen w-full siri-mesh-bg text-foreground overflow-hidden">
	<!-- Sidebar Tabs -->
	<aside class="flex w-64 flex-col border-r border-white/40 bg-[linear-gradient(180deg,rgba(255,255,255,0.72),rgba(248,250,252,0.54)_38%,rgba(239,246,255,0.5))] shadow-[0_24px_60px_rgba(15,23,42,0.14)] backdrop-blur-2xl">
		<div class="shrink-0 p-5 pb-3">
			<a
				href="/"
				class="inline-flex items-center gap-2 rounded-xl border border-white/50 bg-white/50 px-3 py-2 text-[11px] font-medium text-slate-700 shadow-sm transition-all hover:bg-white hover:shadow-md"
			>
				<ArrowLeft class="h-3.5 w-3.5" />
				Back to Chorus
			</a>
			<h2 class="mt-4 text-lg font-bold tracking-tight text-slate-900">Settings</h2>
			<p class="mt-0.5 text-[11px] text-muted-foreground/60">Customize your experience</p>
		</div>
		<nav class="flex-1 space-y-0.5 px-3 py-2">
			{#each tabs as tab}
				<button
					onclick={() => (currentTab = tab.id)}
					class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[13px] font-medium transition-all duration-200 {currentTab === tab.id ? 'bg-white/70 text-slate-900 shadow-sm' : 'text-muted-foreground/70 hover:bg-white/40 hover:text-slate-700'}"
				>
					<tab.icon class="h-4 w-4" />
					{tab.label}
				</button>
			{/each}
		</nav>
		<div class="shrink-0 border-t border-white/40 p-3">
			<button
				onclick={() => (showResetConfirm = true)}
				class="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[11px] font-medium text-muted-foreground/60 transition-all hover:bg-white/50 hover:text-rose-500"
			>
				<RotateCcw class="h-3.5 w-3.5" />
				Reset to defaults
			</button>
		</div>
	</aside>

	<!-- Content -->
	<main class="flex flex-1 flex-col min-w-0 overflow-hidden">
		<div class="shrink-0 border-b border-white/40 bg-white/30 px-8 py-5 backdrop-blur-xl">
			<h3 class="text-base font-semibold text-slate-900 capitalize">{currentTab}</h3>
			<p class="mt-0.5 text-[11px] text-muted-foreground/50">
				{currentTab === 'appearance' && 'Personalize how Chorus looks and feels'}
				{currentTab === 'chat' && 'Configure chat behavior and defaults'}
				{currentTab === 'privacy' && 'Manage your data and privacy preferences'}
				{currentTab === 'advanced' && 'Power-user options and developer tools'}
			</p>
		</div>

		<ScrollArea class="flex-1 px-8 py-6">
			<div class="mx-auto max-w-2xl">
				{#if currentTab === 'appearance'}
					<div class="space-y-8">
						<!-- Theme -->
						<section>
							<label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Sun class="h-4 w-4" />
								Color mode
							</label>
							<p class="mt-1 text-[11px] text-muted-foreground/50">Choose how Chorus looks to you</p>
							<div class="mt-4 grid grid-cols-3 gap-3">
								{#each themeOptions as opt}
									<button
										onclick={() => updateSetting('theme', opt.value)}
										class="flex flex-col items-center gap-2 rounded-2xl border p-4 transition-all duration-200 {localSettings.theme === opt.value ? 'border-primary/40 bg-white/80 shadow-sm' : 'border-white/40 bg-white/30 hover:bg-white/50'}"
									>
										<opt.icon class="h-6 w-6 text-slate-600" />
										<span class="text-xs font-medium text-slate-700">{opt.label}</span>
									</button>
								{/each}
							</div>
						</section>

						<!-- Accent Color -->
						<section>
							<label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Palette class="h-4 w-4" />
								Accent color
							</label>
							<p class="mt-1 text-[11px] text-muted-foreground/50">Personalize the interface accent</p>
							<div class="mt-4 flex flex-wrap gap-3">
								{#each accentOptions as opt}
									<button
										onclick={() => updateSetting('accentColor', opt.value)}
										class="group flex items-center gap-2.5 rounded-2xl border px-4 py-2.5 transition-all duration-200 {localSettings.accentColor === opt.value ? 'border-primary/40 bg-white/80 shadow-sm' : 'border-white/40 bg-white/30 hover:bg-white/50'}"
									>
										<span class="h-5 w-5 rounded-full {opt.color} shadow-sm"></span>
										<span class="text-xs font-medium text-slate-700">{opt.label}</span>
										{#if localSettings.accentColor === opt.value}
											<Check class="h-3.5 w-3.5 text-primary" />
										{/if}
									</button>
								{/each}
							</div>
						</section>

						<!-- Font Size -->
						<section>
							<label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Type class="h-4 w-4" />
								Chat font size
							</label>
							<p class="mt-1 text-[11px] text-muted-foreground/50">Adjust the text size in chat</p>
							<div class="mt-4 flex gap-3">
								{#each fontSizeOptions as opt}
									<button
										onclick={() => updateSetting('fontSize', opt.value)}
										class="flex-1 rounded-2xl border py-2.5 text-xs font-medium transition-all duration-200 {localSettings.fontSize === opt.value ? 'border-primary/40 bg-white/80 text-slate-900 shadow-sm' : 'border-white/40 bg-white/30 text-muted-foreground hover:bg-white/50'}"
									>
										{opt.label}
									</button>
								{/each}
							</div>
						</section>

						<!-- Density -->
						<section>
							<label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Layout class="h-4 w-4" />
								Interface density
							</label>
							<p class="mt-1 text-[11px] text-muted-foreground/50">Control how compact the UI feels</p>
							<div class="mt-4 flex gap-3">
								{#each densityOptions as opt}
									<button
										onclick={() => updateSetting('density', opt.value)}
										class="flex-1 rounded-2xl border py-2.5 text-xs font-medium transition-all duration-200 {localSettings.density === opt.value ? 'border-primary/40 bg-white/80 text-slate-900 shadow-sm' : 'border-white/40 bg-white/30 text-muted-foreground hover:bg-white/50'}"
									>
										{opt.label}
									</button>
								{/each}
							</div>
						</section>
					</div>
				{/if}

				{#if currentTab === 'chat'}
					<div class="space-y-8">
						<!-- Default Context Mode -->
						<section>
							<label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Brain class="h-4 w-4" />
								Default context mode
							</label>
							<p class="mt-1 text-[11px] text-muted-foreground/50">How much context to send with each message</p>
							<div class="mt-4 space-y-2">
								{#each contextModeOptions as opt}
									<button
										onclick={() => updateSetting('defaultContextMode', opt.value)}
										class="flex w-full items-center justify-between rounded-2xl border px-5 py-4 text-left transition-all duration-200 {localSettings.defaultContextMode === opt.value ? 'border-primary/40 bg-white/80 shadow-sm' : 'border-white/40 bg-white/30 hover:bg-white/50'}"
									>
										<div>
											<p class="text-xs font-semibold text-slate-700">{opt.label}</p>
											<p class="text-[11px] text-muted-foreground/50">{opt.desc}</p>
										</div>
										{#if localSettings.defaultContextMode === opt.value}
											<Check class="h-4 w-4 text-primary" />
										{/if}
									</button>
								{/each}
							</div>
						</section>

						<!-- Toggle Settings -->
						<section class="space-y-3">
							<div class="flex items-center justify-between rounded-2xl border border-white/40 bg-white/30 px-5 py-4">
								<div>
									<p class="text-xs font-semibold text-slate-700">Send on Enter</p>
									<p class="text-[11px] text-muted-foreground/50">Press Enter to send messages</p>
								</div>
								<button
									onclick={() => updateSetting('sendOnEnter', !localSettings.sendOnEnter)}
									aria-label="Toggle send on enter"
									class="relative h-5 w-9 rounded-full transition-colors duration-200 {localSettings.sendOnEnter ? 'bg-primary' : 'bg-slate-300'}"
								>
									<span class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 {localSettings.sendOnEnter ? 'translate-x-4' : 'translate-x-0'}"></span>
								</button>
							</div>

							<div class="flex items-center justify-between rounded-2xl border border-white/40 bg-white/30 px-5 py-4">
								<div>
									<p class="text-xs font-semibold text-slate-700">Show agent reasoning</p>
									<p class="text-[11px] text-muted-foreground/50">Display agent thinking steps in the UI</p>
								</div>
								<button
									onclick={() => updateSetting('showAgentReasoning', !localSettings.showAgentReasoning)}
									aria-label="Toggle show agent reasoning"
									class="relative h-5 w-9 rounded-full transition-colors duration-200 {localSettings.showAgentReasoning ? 'bg-primary' : 'bg-slate-300'}"
								>
									<span class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 {localSettings.showAgentReasoning ? 'translate-x-4' : 'translate-x-0'}"></span>
								</button>
							</div>
						</section>
					</div>
				{/if}

				{#if currentTab === 'privacy'}
					<div class="space-y-8">
						<div class="rounded-2xl border border-amber-200/50 bg-amber-50/40 p-5">
							<div class="flex items-start gap-3">
								<AlertTriangle class="mt-0.5 h-5 w-5 text-amber-600" />
								<div>
									<p class="text-xs font-semibold text-amber-800">Privacy Notice</p>
									<p class="mt-1 text-[11px] leading-relaxed text-amber-700/70">
										Chorus stores project data locally in your browser and on the backend server.
										Deleting data here only clears local browser storage.
									</p>
								</div>
							</div>
						</div>

						<section>
							<label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Trash2 class="h-4 w-4" />
								Local data
							</label>
							<p class="mt-1 text-[11px] text-muted-foreground/50">Manage data stored in your browser</p>
							<div class="mt-4 space-y-2">
								{#if showClearHistoryConfirm}
									<div class="flex items-center gap-3 rounded-2xl border border-rose-200/50 bg-rose-50/40 px-5 py-4">
										<span class="text-xs font-semibold text-rose-700">Clear all local history?</span>
										<button
											onclick={handleClearHistory}
											class="ml-auto rounded-lg bg-rose-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-rose-600 transition-colors"
										>
											Confirm
										</button>
										<button
											onclick={() => (showClearHistoryConfirm = false)}
											class="rounded-lg bg-white/70 px-4 py-1.5 text-xs font-medium text-muted-foreground shadow-sm hover:bg-white transition-colors"
										>
											Cancel
										</button>
									</div>
								{:else}
									<button
										onclick={() => (showClearHistoryConfirm = true)}
										class="flex w-full items-center gap-3 rounded-2xl border border-white/40 bg-white/30 px-5 py-4 text-left transition-all hover:bg-white/50"
									>
										<Trash2 class="h-5 w-5 text-rose-500" />
										<div>
											<p class="text-xs font-semibold text-slate-700">Clear local chat history</p>
											<p class="text-[11px] text-muted-foreground/50">Remove cached messages and project IDs</p>
										</div>
									</button>
								{/if}
							</div>
						</section>
					</div>
				{/if}

				{#if currentTab === 'advanced'}
					<div class="space-y-8">
						<section class="space-y-3">
							<div class="flex items-center justify-between rounded-2xl border border-white/40 bg-white/30 px-5 py-4">
								<div>
									<p class="text-xs font-semibold text-slate-700">Auto-approve plans</p>
									<p class="text-[11px] text-muted-foreground/50">Skip plan review and start building immediately</p>
								</div>
								<button
									onclick={() => updateSetting('autoApprovePlans', !localSettings.autoApprovePlans)}
									aria-label="Toggle auto approve plans"
									class="relative h-5 w-9 rounded-full transition-colors duration-200 {localSettings.autoApprovePlans ? 'bg-primary' : 'bg-slate-300'}"
								>
									<span class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 {localSettings.autoApprovePlans ? 'translate-x-4' : 'translate-x-0'}"></span>
								</button>
							</div>

							<div class="flex items-center justify-between rounded-2xl border border-white/40 bg-white/30 px-5 py-4">
								<div>
									<p class="text-xs font-semibold text-slate-700">Show raw events</p>
									<p class="text-[11px] text-muted-foreground/50">Display raw SSE events in the console</p>
								</div>
								<button
									onclick={() => updateSetting('showRawEvents', !localSettings.showRawEvents)}
									aria-label="Toggle show raw events"
									class="relative h-5 w-9 rounded-full transition-colors duration-200 {localSettings.showRawEvents ? 'bg-primary' : 'bg-slate-300'}"
								>
									<span class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 {localSettings.showRawEvents ? 'translate-x-4' : 'translate-x-0'}"></span>
								</button>
							</div>

							<div class="flex items-center justify-between rounded-2xl border border-white/40 bg-white/30 px-5 py-4">
								<div>
									<p class="text-xs font-semibold text-slate-700">Debug mode</p>
									<p class="text-[11px] text-muted-foreground/50">Show additional debug information in the UI</p>
								</div>
								<button
									onclick={() => updateSetting('debugMode', !localSettings.debugMode)}
									aria-label="Toggle debug mode"
									class="relative h-5 w-9 rounded-full transition-colors duration-200 {localSettings.debugMode ? 'bg-primary' : 'bg-slate-300'}"
								>
									<span class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 {localSettings.debugMode ? 'translate-x-4' : 'translate-x-0'}"></span>
								</button>
							</div>
						</section>

						<section class="rounded-2xl border border-white/40 bg-white/30 p-5">
							<div class="flex items-center gap-2 text-sm font-semibold text-slate-700">
								<Terminal class="h-4 w-4" />
								<span>Keyboard shortcuts</span>
							</div>
							<div class="mt-4 space-y-3">
								<div class="flex items-center justify-between text-xs">
									<span class="text-muted-foreground/60">Send message</span>
									<kbd class="rounded-md border border-white/50 bg-white/60 px-2.5 py-1 text-[11px] font-mono text-slate-600">Enter</kbd>
								</div>
								<div class="flex items-center justify-between text-xs">
									<span class="text-muted-foreground/60">New line</span>
									<kbd class="rounded-md border border-white/50 bg-white/60 px-2.5 py-1 text-[11px] font-mono text-slate-600">Shift + Enter</kbd>
								</div>
								<div class="flex items-center justify-between text-xs">
									<span class="text-muted-foreground/60">Close settings</span>
									<kbd class="rounded-md border border-white/50 bg-white/60 px-2.5 py-1 text-[11px] font-mono text-slate-600">Escape</kbd>
								</div>
							</div>
						</section>
					</div>
				{/if}
			</div>
		</ScrollArea>
	</main>
</div>

<!-- Reset Confirmation Dialog -->
{#if showResetConfirm}
	<div class="fixed inset-0 z-[110] flex items-center justify-center">
		<button
			type="button"
			class="absolute inset-0 bg-black/30 backdrop-blur-sm"
			onclick={() => (showResetConfirm = false)}
			aria-label="Cancel reset"
		></button>
		<div class="relative w-96 rounded-2xl border border-white/50 bg-white/90 p-6 shadow-2xl backdrop-blur-xl">
			<div class="flex items-center gap-2 text-rose-600">
				<RotateCcw class="h-5 w-5" />
				<h3 class="text-base font-bold">Reset all settings?</h3>
			</div>
			<p class="mt-3 text-xs leading-relaxed text-slate-600">
				This will restore all settings to their default values. Your projects and chat history will not be affected.
			</p>
			<div class="mt-5 flex justify-end gap-2">
				<button
					onclick={() => (showResetConfirm = false)}
					class="rounded-xl border border-white/50 bg-white/60 px-4 py-2 text-xs font-medium text-muted-foreground shadow-sm hover:bg-white transition-colors"
				>
					Cancel
				</button>
				<button
					onclick={handleReset}
					class="rounded-xl bg-rose-500 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-rose-600 transition-colors"
				>
					Reset
				</button>
			</div>
		</div>
	</div>
{/if}
