import { writable } from 'svelte/store';

export type ThemeMode = 'light' | 'dark' | 'system';
export type AccentColor = 'purple' | 'blue' | 'green' | 'orange' | 'rose' | 'slate';
export type FontSize = 'small' | 'default' | 'large';
export type Density = 'compact' | 'default' | 'comfortable';
export type ContextMode = 'auto' | 'lean' | 'full';

export interface AppSettings {
	theme: ThemeMode;
	accentColor: AccentColor;
	fontSize: FontSize;
	density: Density;
	defaultContextMode: ContextMode;
	sendOnEnter: boolean;
	showAgentReasoning: boolean;
	showRawEvents: boolean;
	autoApprovePlans: boolean;
	debugMode: boolean;
}

const DEFAULT_SETTINGS: AppSettings = {
	theme: 'system',
	accentColor: 'purple',
	fontSize: 'default',
	density: 'default',
	defaultContextMode: 'auto',
	sendOnEnter: true,
	showAgentReasoning: true,
	showRawEvents: false,
	autoApprovePlans: false,
	debugMode: false,
};

const STORAGE_KEY = 'chorus.settings';

const IS_BROWSER = typeof window !== 'undefined';

function loadSettings(): AppSettings {
	if (!IS_BROWSER) return { ...DEFAULT_SETTINGS };
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) {
			const parsed = JSON.parse(raw);
			return { ...DEFAULT_SETTINGS, ...parsed };
		}
	} catch {
		// ignore
	}
	return { ...DEFAULT_SETTINGS };
}

function saveSettings(settings: AppSettings) {
	if (!IS_BROWSER) return;
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
	} catch {
		// ignore
	}
}

const accentColorMap: Record<AccentColor, string> = {
	purple: '280 80% 60%',
	blue: '217 91% 60%',
	green: '160 84% 39%',
	orange: '24 95% 53%',
	rose: '346 84% 60%',
	slate: '215 25% 27%',
};

function applyTheme(theme: ThemeMode) {
	if (!IS_BROWSER) return;
	const root = document.documentElement;
	const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
	const isDark = theme === 'dark' || (theme === 'system' && prefersDark);

	if (isDark) {
		root.classList.add('dark');
		root.style.setProperty('--background', '222.2 84% 4.9%');
		root.style.setProperty('--foreground', '210 40% 98%');
		root.style.setProperty('--card', '217.2 32.6% 17.5%');
		root.style.setProperty('--card-foreground', '210 40% 98%');
		root.style.setProperty('--muted', '217.2 32.6% 17.5%');
		root.style.setProperty('--muted-foreground', '215 20.2% 65.1%');
		root.style.setProperty('--border', '217.2 32.6% 17.5%');
	} else {
		root.classList.remove('dark');
		root.style.setProperty('--background', '0 0% 100%');
		root.style.setProperty('--foreground', '222.2 84% 4.9%');
		root.style.setProperty('--card', '210 40% 98%');
		root.style.setProperty('--card-foreground', '222.2 84% 4.9%');
		root.style.setProperty('--muted', '210 40% 96.1%');
		root.style.setProperty('--muted-foreground', '215.4 16.3% 46.9%');
		root.style.setProperty('--border', '214.3 31.8% 91.4%');
	}
}

function applyAccentColor(color: AccentColor) {
	if (!IS_BROWSER) return;
	const root = document.documentElement;
	const hsl = accentColorMap[color];
	root.style.setProperty('--primary', hsl);
	root.style.setProperty('--ring', hsl);
}

function applyFontSize(size: FontSize) {
	if (!IS_BROWSER) return;
	const root = document.documentElement;
	const scale = size === 'small' ? '0.875' : size === 'large' ? '1.125' : '1';
	root.style.setProperty('--font-scale', scale);
}

function applyDensity(density: Density) {
	if (!IS_BROWSER) return;
	const root = document.documentElement;
	const spacing = density === 'compact' ? '0.75' : density === 'comfortable' ? '1.25' : '1';
	root.style.setProperty('--density-scale', spacing);
}

function applySettings(s: AppSettings) {
	applyTheme(s.theme);
	applyAccentColor(s.accentColor);
	applyFontSize(s.fontSize);
	applyDensity(s.density);
}

function createSettingsStore() {
	const initial = loadSettings();
	const { subscribe, set, update } = writable<AppSettings>(initial);

	if (IS_BROWSER) {
		applySettings(initial);
	}

	return {
		subscribe,
		set: (value: AppSettings) => {
			set(value);
			if (IS_BROWSER) {
				saveSettings(value);
				applySettings(value);
			}
		},
		update: (updater: (s: AppSettings) => AppSettings) => {
			update((s) => {
				const next = updater(s);
				if (IS_BROWSER) {
					saveSettings(next);
					applySettings(next);
				}
				return next;
			});
		},
		reset: () => {
			set({ ...DEFAULT_SETTINGS });
			if (IS_BROWSER) {
				saveSettings({ ...DEFAULT_SETTINGS });
				applySettings({ ...DEFAULT_SETTINGS });
			}
		},
	};
}

export const settings = createSettingsStore();

// Listen for system theme changes
if (IS_BROWSER) {
	const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
	mediaQuery.addEventListener('change', () => {
		const current = loadSettings();
		if (current.theme === 'system') {
			applyTheme('system');
		}
	});
}
