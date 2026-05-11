<script lang="ts">
	let {
		fill = 'url(#hexGrad)',
		stroke = 'rgba(0,0,0,0.1)',
		innerFill = 'white',
		size = 28,
		gradId = 'hexGrad'
	}: {
		fill?: string;
		stroke?: string;
		innerFill?: string;
		size?: number;
		gradId?: string;
	} = $props();
</script>

<span class="hex-mark" style="width: {size}px; height: {size}px;">
	<svg viewBox="0 0 32 32" fill="none">
		<path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z" fill={fill} {stroke} stroke-width="1"/>
		<path d="M16 9 L22 12.5 L22 19.5 L16 23 L10 19.5 L10 12.5 Z" fill={innerFill}/>
		{#if fill.startsWith('url(')}
			<defs>
				<linearGradient id={gradId} x1="0" y1="0" x2="1" y2="1">
					<stop offset="0" stop-color="#a78bfa"/>
					<stop offset="1" stop-color="#7c3aed"/>
				</linearGradient>
			</defs>
		{/if}
	</svg>
</span>
