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

	async function renderMarkdown() {
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
				return `<div class="chat-mermaid not-prose overflow-x-auto rounded-2xl border border-cyan-200/35 bg-[linear-gradient(180deg,rgba(236,254,255,0.76),rgba(255,255,255,0.92))] p-3 shadow-[0_10px_24px_rgba(14,165,233,0.10)]" data-mermaid="${escapeAttr(text)}"><div class="text-[11px] font-medium text-cyan-700/70">Rendering diagram...</div></div>`;
			}

			return `<pre class="not-prose overflow-x-auto rounded-2xl border border-black/10 bg-slate-950/95 p-3 text-[12px] leading-6 text-slate-100 shadow-[0_10px_24px_rgba(15,23,42,0.16)]"><code class="${normalizedLang ? `language-${escapeAttr(normalizedLang)}` : ''}">${escapeHtml(text)}</code></pre>`;
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
			const diagramId = `chat-mermaid-${currentToken}-${i}`;
			try {
				const { svg } = await mermaid.render(diagramId, diagram);
				node.innerHTML = DOMPurify.sanitize(svg, {
					USE_PROFILES: { svg: true, svgFilters: true }
				});
			} catch (error) {
				node.innerHTML = `
					<div class="rounded-xl border border-rose-200/70 bg-rose-50/90 p-3 text-xs text-rose-700">
						Mermaid diagram failed to render.
					</div>
					<pre class="mt-2 overflow-x-auto rounded-xl bg-slate-950/95 p-3 text-xs text-slate-100">${escapeHtml(diagram)}</pre>
				`;
				console.error('Failed to render Mermaid diagram in chat:', error);
			}
		}
	}

	$effect(() => {
		source;
		void renderMarkdown();
	});
</script>

<div
	bind:this={container}
	class="chat-markdown prose prose-slate max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-p:my-0 prose-p:leading-7 prose-ul:my-2 prose-ol:my-2 prose-li:my-0 prose-strong:font-semibold prose-a:break-words prose-table:w-full prose-table:border-collapse prose-th:border prose-th:border-white/40 prose-th:bg-white/70 prose-th:px-3 prose-th:py-2 prose-td:border prose-td:border-white/30 prose-td:px-3 prose-td:py-2 prose-code:rounded prose-code:bg-black/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:font-mono prose-code:text-[0.9em] prose-pre:my-2 prose-pre:p-0"
>
	{#if renderedHtml}
		{@html renderedHtml}
	{:else}
		<p class="whitespace-pre-wrap">{source}</p>
	{/if}
</div>
