<script lang="ts">
	import { browser } from '$app/environment';
	import { tick } from 'svelte';
	import createDOMPurify from 'dompurify';

	let { source = '' }: { source?: string } = $props();

	let container = $state<HTMLDivElement | null>(null);
	let renderedHtml = $state('');
	let renderToken = 0;

	function escapeHtml(value: string): string {
		return value
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
	}

	function escapeAttr(value: string): string {
		return escapeHtml(value).replace(/`/g, '&#96;');
	}

	async function renderPreview() {
		if (!browser) return;
		const currentToken = ++renderToken;

		const [{ marked }, mermaidModule] = await Promise.all([
			import('marked'),
			import('mermaid')
		]);

		const DOMPurify = createDOMPurify(window);
		const renderer = new marked.Renderer();

		renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
			const normalizedLang = (lang || '').trim().toLowerCase();
			if (normalizedLang === 'mermaid') {
				return `<div class="plan-mermaid" data-mermaid="${escapeAttr(text)}"><div class="plan-rendering">Rendering diagram...</div></div>`;
			}

			return `<pre class="plan-code"><code class="${normalizedLang ? `language-${escapeAttr(normalizedLang)}` : ''}">${escapeHtml(text)}</code></pre>`;
		};

		const normalized = source.replace(/^[\u200B\u200C\u200D\u200E\u200F\uFEFF]/, '');
		const html = await Promise.resolve(marked.parse(normalized, {
			renderer,
			gfm: true,
			breaks: true
		}));

		const sanitized = DOMPurify.sanitize(html, {
			ADD_ATTR: ['data-mermaid']
		});

		if (currentToken !== renderToken) return;
		renderedHtml = sanitized;
		await tick();

		if (!container) return;

		const mermaid = mermaidModule.default;
		mermaid.initialize({
			startOnLoad: false,
			securityLevel: 'strict',
			theme: 'neutral',
			flowchart: {
				useMaxWidth: true
			}
		});

		const nodes = Array.from(container.querySelectorAll<HTMLElement>('[data-mermaid]'));
		for (let i = 0; i < nodes.length; i += 1) {
			const node = nodes[i];
			const diagram = node.dataset.mermaid || '';
			const diagramId = `plan-mermaid-${currentToken}-${i}`;
			try {
				const { svg } = await mermaid.render(diagramId, diagram);
				node.innerHTML = DOMPurify.sanitize(svg, {
					USE_PROFILES: { svg: true, svgFilters: true }
				});
			} catch (error) {
				node.innerHTML = `
					<div class="plan-mermaid-error">
						Mermaid diagram failed to render.
					</div>
					<pre class="plan-code">${escapeHtml(diagram)}</pre>
				`;
				console.error('Failed to render Mermaid diagram:', error);
			}
		}
	}

	$effect(() => {
		source;
		void renderPreview();
	});
</script>

<div
	bind:this={container}
	class="plan-spec-preview"
>
	{#if renderedHtml}
		{@html renderedHtml}
	{:else}
		<div class="plan-preview-empty">
			<p>Plan preview will appear here</p>
		</div>
	{/if}
</div>

<style>
	.plan-spec-preview {
		padding: 18px;
		color: var(--ink-1);
		font-size: 14px;
		line-height: 1.65;
	}

	.plan-spec-preview :global(h1),
	.plan-spec-preview :global(h2),
	.plan-spec-preview :global(h3) {
		font-family: var(--font-display);
		font-weight: 400;
		letter-spacing: -0.014em;
		color: var(--ink-0);
		line-height: 1.05;
		margin: 1.15em 0 0.45em;
	}

	.plan-spec-preview :global(h1) { font-size: 38px; margin-top: 0; }
	.plan-spec-preview :global(h2) { font-size: 29px; }
	.plan-spec-preview :global(h3) { font-size: 22px; }

	.plan-spec-preview :global(p) { margin: 0.55em 0; color: var(--ink-2); }
	.plan-spec-preview :global(ul),
	.plan-spec-preview :global(ol) { margin: 0.55em 0 0.9em; padding-left: 1.25rem; }
	.plan-spec-preview :global(li) { margin: 0.25em 0; }
	.plan-spec-preview :global(strong) { color: var(--violet-d); font-weight: 600; }
	.plan-spec-preview :global(code) {
		border: 1px solid var(--line);
		border-radius: 5px;
		background: rgba(255,255,255,0.72);
		padding: 1px 5px;
		font-family: var(--font-mono);
		font-size: 0.86em;
		color: var(--ink-1);
	}

	.plan-spec-preview :global(table) {
		width: 100%;
		border-collapse: collapse;
		margin: 14px 0;
		overflow: hidden;
		border-radius: 10px;
		font-size: 13px;
	}
	.plan-spec-preview :global(th),
	.plan-spec-preview :global(td) {
		border: 1px solid var(--line);
		padding: 8px 10px;
		text-align: left;
	}
	.plan-spec-preview :global(th) {
		background: rgba(255,255,255,0.72);
		color: var(--ink-0);
		font-weight: 600;
	}

	.plan-spec-preview :global(.plan-code) {
		margin: 12px 0;
		overflow-x: auto;
		border: 1px solid rgba(255,255,255,0.12);
		border-radius: 12px;
		background: var(--ink-0);
		padding: 14px;
		color: var(--paper-0);
		box-shadow: 0 14px 34px rgba(20,18,32,0.16);
	}
	.plan-spec-preview :global(.plan-code code) {
		border: 0;
		background: transparent;
		padding: 0;
		color: inherit;
		font-size: 12px;
		line-height: 1.6;
	}

	.plan-spec-preview :global(.plan-mermaid) {
		margin: 14px 0;
		overflow-x: auto;
		border: 1px solid rgba(255,255,255,0.62);
		border-radius: 14px;
		background:
			linear-gradient(180deg, rgba(255,255,255,0.74), rgba(255,255,255,0.58)),
			radial-gradient(80% 140% at 100% 0%, oklch(80% 0.13 220 / 0.20), transparent 62%);
		padding: 16px;
		box-shadow: var(--shadow-1);
	}

	:global(.plan-rendering),
	:global(.plan-mermaid-error),
	.plan-preview-empty {
		border: 1px dashed var(--line-strong);
		border-radius: 12px;
		background: rgba(255,255,255,0.56);
		padding: 18px;
		text-align: center;
		color: var(--ink-5);
		font-size: 13px;
	}

	.plan-preview-empty {
		display: grid;
		place-items: center;
		min-height: 260px;
	}
	.plan-preview-empty p { margin: 0; color: var(--ink-4); font-weight: 500; }
</style>
