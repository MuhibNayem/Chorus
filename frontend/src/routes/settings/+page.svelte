<svelte:head>
	<title>Settings — Chorus</title>
	<style>
		body { background: var(--paper-1); }

		.app-shell { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
		@media (max-width: 980px) { .app-shell { grid-template-columns: 1fr; } .side { display: none; } }

		/* SIDEBAR */
		.side {
			border-right: 1px solid var(--line);
			background: var(--paper-0);
			display: flex; flex-direction: column;
			padding: 22px 18px;
			position: sticky; top: 0; height: 100vh;
		}
		.side .top {
			display: flex; align-items: center; gap: 10px;
			margin-bottom: 20px;
		}
		.side .top a {
			width: 32px; height: 32px;
			border-radius: 10px;
			border: 1px solid var(--line);
			display: inline-flex; align-items: center; justify-content: center;
			color: var(--ink-3); transition: all 180ms ease;
		}
		.side .top a:hover { background: var(--paper-1); color: var(--ink-0); }
		.side .top .brand-r {
			display: flex; align-items: center; gap: 8px;
			font-weight: 600; font-size: 15px; letter-spacing: -0.01em;
		}

		.side h4 {
			font-family: var(--font-mono); font-size: 10.5px;
			letter-spacing: 0.14em; text-transform: uppercase;
			color: var(--ink-5); margin: 18px 8px 8px; font-weight: 500;
		}
		.nav-section { display: flex; flex-direction: column; gap: 1px; }
		.nav-item {
			display: flex; align-items: center; gap: 11px;
			padding: 9px 12px; border-radius: 10px;
			font-size: 13.5px; color: var(--ink-3);
			cursor: pointer; transition: all 160ms ease;
			border: 1px solid transparent;
		}
		.nav-item:hover { background: var(--paper-1); color: var(--ink-0); }
		.nav-item.active {
			background: var(--ink-0); color: white;
			border-color: var(--ink-0);
			box-shadow: 0 4px 12px rgba(20,18,32,0.10);
		}
		.nav-item .ix {
			font-family: var(--font-mono); font-size: 10px;
			color: var(--ink-5); letter-spacing: 0.08em;
			margin-left: auto;
		}
		.nav-item.active .ix { color: var(--violet-2); }
		.nav-item svg { width: 16px; height: 16px; flex-shrink: 0; }

		.side .me {
			margin-top: auto;
			padding: 12px;
			border: 1px solid var(--line);
			border-radius: 14px;
			display: flex; align-items: center; gap: 10px;
			background: var(--paper-1);
		}
		.me .av {
			width: 34px; height: 34px; border-radius: 50%;
			background: conic-gradient(from 130deg, oklch(70% 0.18 295), oklch(75% 0.15 220), oklch(78% 0.18 30));
			flex-shrink: 0;
		}
		.me .info { display: flex; flex-direction: column; min-width: 0; flex: 1;}
		.me .info b { font-size: 13px; font-weight: 500; color: var(--ink-0); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
		.me .info span { font-size: 11px; color: var(--ink-5); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}

		/* MAIN */
		main { padding: 0; }
		.page-head {
			padding: 32px 48px 28px;
			border-bottom: 1px solid var(--line);
			background: var(--paper-0);
			position: sticky; top: 0; z-index: 5;
			backdrop-filter: blur(20px);
		}
		.page-head .crumbs {
			display: flex; align-items: center; gap: 8px;
			font-family: var(--font-mono); font-size: 11px;
			color: var(--ink-5); letter-spacing: 0.08em;
			margin-bottom: 10px;
		}
		.page-head .crumbs span.cur { color: var(--ink-0); }
		.page-head h1 {
			font-family: var(--font-display);
			font-weight: 400;
			font-size: 40px; line-height: 1; letter-spacing: -0.02em;
			margin: 0 0 8px;
		}
		.page-head .lede { color: var(--ink-4); font-size: 14px; max-width: 60ch; margin: 0; }

		.body-wrap { padding: 32px 48px 80px; max-width: 920px; }

		.section {
			border: 1px solid var(--line);
			background: var(--paper-0);
			border-radius: 20px;
			margin-bottom: 24px;
			overflow: hidden;
		}
		.section header {
			padding: 22px 28px 18px;
			border-bottom: 1px solid var(--line);
			display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;
		}
		.section header h3 {
			font-size: 16px; font-weight: 500;
			letter-spacing: -0.01em; margin: 0;
		}
		.section header p {
			font-size: 13px; color: var(--ink-4);
			margin: 4px 0 0;
		}
		.section .body { padding: 0; }

		.row {
			display: grid; grid-template-columns: 1.2fr 1.6fr;
			gap: 24px; padding: 22px 28px;
			border-bottom: 1px solid var(--line);
			align-items: start;
		}
		.row:last-child { border-bottom: 0; }
		.row .label-col h4 {
			font-size: 13.5px; font-weight: 500; margin: 0 0 4px;
			color: var(--ink-1);
		}
		.row .label-col p {
			font-size: 12.5px; color: var(--ink-4); margin: 0; line-height: 1.5;
		}

		/* Theme cards */
		.theme-grid {
			display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
		}
		.theme {
			border: 1.5px solid var(--line);
			border-radius: 14px;
			padding: 6px;
			cursor: pointer;
			transition: all 180ms ease;
			background: var(--paper-0);
		}
		.theme:hover { border-color: var(--ink-3); }
		.theme.on {
			border-color: var(--violet);
			box-shadow: 0 0 0 4px oklch(70% 0.18 295 / 0.10);
		}
		.theme .preview {
			height: 76px; border-radius: 10px;
			margin-bottom: 8px;
			overflow: hidden; position: relative;
			border: 1px solid var(--line);
		}
		.theme.light .preview { background: linear-gradient(180deg, #fafafa, #ffffff); }
		.theme.light .preview::before {
			content: ""; position: absolute; left: 8px; top: 8px; right: 8px; height: 8px;
			background: rgba(0,0,0,0.04); border-radius: 4px;
		}
		.theme.light .preview::after {
			content: ""; position: absolute; left: 8px; top: 22px; width: 60%; height: 6px;
			background: rgba(0,0,0,0.07); border-radius: 3px;
		}
		.theme.dark .preview { background: linear-gradient(180deg, #0e0c14, #1a1622); }
		.theme.dark .preview::before {
			content: ""; position: absolute; left: 8px; top: 8px; right: 8px; height: 8px;
			background: rgba(255,255,255,0.10); border-radius: 4px;
		}
		.theme.dark .preview::after {
			content: ""; position: absolute; left: 8px; top: 22px; width: 60%; height: 6px;
			background: oklch(70% 0.18 295 / 0.6); border-radius: 3px;
		}
		.theme.system .preview { background: linear-gradient(90deg, #fafafa 50%, #0e0c14 50%); }
		.theme .label {
			display: flex; justify-content: space-between; align-items: center;
			padding: 4px 6px 2px;
			font-size: 12px; font-weight: 500;
		}
		.theme .label .check {
			opacity: 0; color: var(--violet);
		}
		.theme.on .label .check { opacity: 1; }

		/* Accent picker */
		.accent-grid {
			display: flex; flex-wrap: wrap; gap: 8px;
		}
		.accent {
			cursor: pointer;
			width: 36px; height: 36px;
			border-radius: 50%;
			position: relative;
			box-shadow: inset 0 0 0 2px white, 0 0 0 1.5px var(--line);
			transition: all 180ms ease;
		}
		.accent.on { box-shadow: inset 0 0 0 2px white, 0 0 0 2px var(--ink-0); transform: scale(1.06); }
		.accent::after {
			content: ""; position: absolute; left: 50%; top: 50%;
			transform: translate(-50%,-50%);
			width: 10px; height: 10px; border-radius: 50%; background: white;
			opacity: 0; transition: opacity 160ms ease;
		}
		.accent.on::after { opacity: 1; }

		/* Segment control */
		.segment {
			display: inline-flex;
			border: 1px solid var(--line);
			border-radius: 12px;
			padding: 3px;
			background: var(--paper-1);
			gap: 0;
		}
		.segment button {
			border: 0; background: transparent;
			padding: 7px 14px; border-radius: 9px;
			font-size: 12.5px; font-weight: 500;
			color: var(--ink-4); cursor: pointer;
			transition: all 180ms ease;
		}
		.segment button.on {
			background: var(--paper-0); color: var(--ink-0);
			box-shadow: 0 1px 4px rgba(20,18,32,0.06), 0 0 0 1px var(--line);
		}

		/* Toggle */
		.toggle {
			width: 38px; height: 22px;
			background: var(--paper-2);
			border-radius: 999px;
			position: relative;
			cursor: pointer;
			transition: background 180ms ease;
			flex-shrink: 0;
		}
		.toggle::after {
			content: ""; position: absolute;
			top: 2px; left: 2px;
			width: 18px; height: 18px;
			background: white; border-radius: 50%;
			box-shadow: 0 1px 3px rgba(0,0,0,0.12);
			transition: transform 200ms cubic-bezier(0.4,0,0.2,1);
		}
		.toggle.on { background: var(--ink-0); }
		.toggle.on::after { transform: translateX(16px); }

		.row-flex {
			display: flex; align-items: center; justify-content: space-between;
			padding: 16px 28px;
			border-bottom: 1px solid var(--line);
		}
		.row-flex:last-child { border-bottom: 0; }
		.row-flex .info { flex: 1; }
		.row-flex .info h4 { font-size: 13.5px; font-weight: 500; margin: 0 0 2px; }
		.row-flex .info p { font-size: 12.5px; color: var(--ink-4); margin: 0; }
		.row-flex .info .meta {
			display: flex; gap: 12px; align-items: center; margin-top: 4px;
			font-family: var(--font-mono); font-size: 10.5px;
			letter-spacing: 0.08em; color: var(--ink-5);
		}

		/* Context cards */
		.ctx-grid {
			display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
		}
		.ctx {
			cursor: pointer;
			border: 1.5px solid var(--line);
			border-radius: 14px;
			padding: 14px;
			transition: all 180ms ease;
			display: flex; flex-direction: column; gap: 6px;
			position: relative;
		}
		.ctx:hover { border-color: var(--ink-3); }
		.ctx.on {
			border-color: var(--ink-0);
			background: var(--paper-1);
		}
		.ctx .ix {
			font-family: var(--font-mono); font-size: 10px;
			letter-spacing: 0.10em; color: var(--ink-5);
		}
		.ctx h5 { margin: 0; font-size: 14px; font-weight: 500; letter-spacing: -0.01em; }
		.ctx p { margin: 0; font-size: 12px; color: var(--ink-4); line-height: 1.45; }
		.ctx .check {
			position: absolute; top: 12px; right: 12px;
			width: 16px; height: 16px; border-radius: 50%;
			border: 1.5px solid var(--line-strong);
			display: inline-flex; align-items: center; justify-content: center;
		}
		.ctx.on .check { border-color: var(--ink-0); background: var(--ink-0); }
		.ctx.on .check::after { content: "✓"; color: white; font-size: 10px; }

		/* MiniMax */
		.quota {
			border: 1px solid var(--line);
			border-radius: 16px;
			padding: 18px;
			background: linear-gradient(180deg, var(--paper-0), var(--paper-1));
		}
		.quota .top {
			display: flex; justify-content: space-between; align-items: baseline;
		}
		.quota .top .l { font-family: var(--font-mono); font-size: 11px; color: var(--ink-5); letter-spacing: 0.10em; }
		.quota .top .v {
			font-family: var(--font-display);
			font-size: 32px; line-height: 1; letter-spacing: -0.02em;
		}
		.quota .top .v em { color: var(--violet-d); font-style: italic; }
		.quota .bar {
			margin-top: 12px;
			height: 6px; background: var(--paper-2); border-radius: 3px; overflow: hidden;
			position: relative;
		}
		.quota .bar .fill {
			height: 100%;
			background: linear-gradient(90deg, var(--violet-d), oklch(75% 0.15 220));
			border-radius: 3px;
			width: 38%;
		}
		.quota .meta {
			margin-top: 10px;
			display: flex; justify-content: space-between;
			font-family: var(--font-mono); font-size: 10.5px;
			color: var(--ink-5); letter-spacing: 0.06em;
		}

		/* Plan card */
		.plan-card {
			border: 1px solid var(--line);
			border-radius: 16px;
			padding: 22px;
			background: var(--ink-0);
			color: white;
			display: grid; grid-template-columns: 1fr auto;
			gap: 24px; align-items: center;
			position: relative; overflow: hidden;
		}
		.plan-card::before {
			content: ""; position: absolute; inset: 0;
			background: radial-gradient(50% 80% at 100% 0%, oklch(70% 0.20 295 / 0.30), transparent 60%);
		}
		.plan-card > * { position: relative; z-index: 1; }
		.plan-card .tag {
			font-family: var(--font-mono); font-size: 10.5px;
			color: var(--violet-2); letter-spacing: 0.14em;
		}
		.plan-card h3 {
			margin: 6px 0 4px; font-size: 22px; font-weight: 500;
			color: white; letter-spacing: -0.01em;
		}
		.plan-card p { color: rgba(255,255,255,0.65); font-size: 13px; margin: 0; }

		/* Danger card */
		.danger {
			border: 1px solid oklch(85% 0.04 25);
			background: oklch(98% 0.012 25);
			border-radius: 14px;
			padding: 18px 22px;
			display: flex; align-items: center; justify-content: space-between; gap: 24px;
		}
		.danger:not(:last-child) { margin-bottom: 10px; }
		.danger .info h4 { color: oklch(40% 0.18 25); font-size: 14px; margin: 0 0 4px; font-weight: 500; }
		.danger .info p { color: oklch(45% 0.10 25); font-size: 12.5px; margin: 0; line-height: 1.5; max-width: 56ch; }
		.danger button {
			border: 1px solid oklch(72% 0.18 25);
			background: white;
			color: oklch(45% 0.20 25);
			padding: 9px 16px; border-radius: 10px;
			font-size: 12.5px; font-weight: 500;
			cursor: pointer; transition: all 180ms ease;
			flex-shrink: 0;
		}
		.danger button:hover {
			background: oklch(60% 0.20 25); color: white; border-color: oklch(60% 0.20 25);
		}

		.save-bar {
			position: sticky; bottom: 24px;
			margin: 32px auto 0; max-width: 920px;
			background: var(--ink-0); color: white;
			border-radius: 16px;
			padding: 14px 20px;
			display: flex; align-items: center; justify-content: space-between; gap: 16px;
			box-shadow: 0 24px 60px rgba(20,18,32,0.30), 0 0 0 1px rgba(167, 139, 250, 0.20);
		}
		.save-bar .l {
			font-size: 13px; color: rgba(255,255,255,0.85); display: flex; gap: 12px; align-items: center;
		}
		.save-bar .l .dot {
			width: 8px; height: 8px; border-radius: 50%;
			background: var(--violet-2);
			box-shadow: 0 0 12px var(--violet-2);
			animation: pulse 1.4s ease-in-out infinite;
		}
		.save-bar .actions { display: flex; gap: 8px; }
		.save-bar button {
			padding: 9px 16px; border-radius: 10px;
			font-size: 12.5px; font-weight: 500; cursor: pointer;
			border: 1px solid rgba(255,255,255,0.15);
			background: transparent; color: white;
		}
		.save-bar button.primary {
			background: white; color: var(--ink-0); border-color: white;
		}
	</style>
</svelte:head>

<div class="app-shell" data-screen-label="Settings — App shell">

	<!-- SIDEBAR -->
	<aside class="side">
		<div class="top">
			<a href="/" title="Back to Chorus">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
			</a>
			<span class="brand-r">
				<span class="hex-mark"><svg viewBox="0 0 32 32" fill="none">
					<path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z" fill="url(#g4)"/>
					<path d="M16 9 L22 12.5 L22 19.5 L16 23 L10 19.5 L10 12.5 Z" fill="white"/>
					<defs><linearGradient id="g4" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs>
				</svg></span>
				Settings
			</span>
		</div>

		<h4>Workspace</h4>
		<div class="nav-section">
			<div class="nav-item active" data-tab="appearance">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg>
				Appearance <span class="ix">01</span>
			</div>
			<div class="nav-item" data-tab="account">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
				Account <span class="ix">02</span>
			</div>
			<div class="nav-item" data-tab="swarm">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/><line x1="12" y1="22" x2="12" y2="15.5"/></svg>
				Swarm &amp; agents <span class="ix">03</span>
			</div>
			<div class="nav-item" data-tab="billing">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
				Billing <span class="ix">04</span>
			</div>
		</div>

		<h4>System</h4>
		<div class="nav-section">
			<div class="nav-item" data-tab="integrations">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
				Integrations <span class="ix">05</span>
			</div>
			<div class="nav-item" data-tab="security">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
				Security <span class="ix">06</span>
			</div>
			<div class="nav-item" data-tab="advanced">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
				Advanced <span class="ix">07</span>
			</div>
		</div>

		<div class="me">
			<span class="av"></span>
			<div class="info">
				<b>Asha Iqbal</b>
				<span>Studio · 6 agents</span>
			</div>
			<button style="background:transparent; border:0; padding:6px; cursor:pointer; color: var(--ink-5);">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>
			</button>
		</div>
	</aside>

	<!-- MAIN -->
	<main>
		<div class="page-head">
			<div class="crumbs">
				<span>SETTINGS</span> <span>/</span> <span class="cur" id="crumbCur">APPEARANCE</span>
			</div>
			<h1 id="pageTitle">Appearance</h1>
			<p class="lede" id="pageLede">Personalize how Chorus renders the mesh, the chat, and every code surface in between.</p>
		</div>

		<div class="body-wrap">

			<!-- SECTION: Theme -->
			<div class="section">
				<header>
					<div>
						<h3>Color mode</h3>
						<p>Match your OS, or override per-device.</p>
					</div>
				</header>
				<div class="body">
					<div class="row">
						<div class="label-col">
							<h4>Theme</h4>
							<p>Light keeps the mesh paper-bright. Dark goes void-black with full bloom on agent activity.</p>
						</div>
						<div class="theme-grid">
							<div class="theme light on">
								<div class="preview"></div>
								<div class="label">Light <span class="check">✓</span></div>
							</div>
							<div class="theme dark">
								<div class="preview"></div>
								<div class="label">Dark <span class="check">✓</span></div>
							</div>
							<div class="theme system">
								<div class="preview"></div>
								<div class="label">System <span class="check">✓</span></div>
							</div>
						</div>
					</div>

					<div class="row">
						<div class="label-col">
							<h4>Accent</h4>
							<p>The conducting color — used for active agents, focus rings, the send button, and the bloom around running tasks.</p>
						</div>
						<div>
							<div class="accent-grid">
								<span class="accent on" style="background: oklch(58% 0.22 295);"></span>
								<span class="accent" style="background: oklch(60% 0.20 250);"></span>
								<span class="accent" style="background: oklch(62% 0.18 200);"></span>
								<span class="accent" style="background: oklch(60% 0.18 160);"></span>
								<span class="accent" style="background: oklch(72% 0.18 60);"></span>
								<span class="accent" style="background: oklch(62% 0.22 25);"></span>
								<span class="accent" style="background: oklch(60% 0.18 340);"></span>
								<span class="accent" style="background: oklch(40% 0.02 280);"></span>
							</div>
							<p style="font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-5); letter-spacing: 0.08em; margin-top: 12px;">CURRENT &middot; oklch(58% 0.22 295) &middot; CHORUS VIOLET</p>
						</div>
					</div>

					<div class="row">
						<div class="label-col">
							<h4>Density</h4>
							<p>Compress for laptop / Pro Display tuning, comfortable for studio sessions.</p>
						</div>
						<div class="segment">
							<button>Compact</button>
							<button class="on">Default</button>
							<button>Comfortable</button>
						</div>
					</div>

					<div class="row">
						<div class="label-col">
							<h4>Editor font size</h4>
							<p>Affects code view and SPEC.md preview.</p>
						</div>
						<div class="segment">
							<button>13&nbsp;px</button>
							<button class="on">14&nbsp;px</button>
							<button>15&nbsp;px</button>
							<button>16&nbsp;px</button>
						</div>
					</div>
				</div>
			</div>

			<!-- SECTION: Chat -->
			<div class="section">
				<header>
					<div>
						<h3>Conducting the swarm</h3>
						<p>Defaults applied to every new prompt.</p>
					</div>
				</header>
				<div class="body">
					<div class="row">
						<div class="label-col">
							<h4>Default context mode</h4>
							<p>Lean keeps each agent's context tight (faster, cheaper). Full hands the entire workspace to every agent.</p>
						</div>
						<div class="ctx-grid">
							<div class="ctx">
								<span class="ix">01</span>
								<h5>Lean</h5>
								<p>Just the spec &amp; touched files.</p>
								<span class="check"></span>
							</div>
							<div class="ctx on">
								<span class="ix">02</span>
								<h5>Auto</h5>
								<p>Chorus picks per task.</p>
								<span class="check"></span>
							</div>
							<div class="ctx">
								<span class="ix">03</span>
								<h5>Full</h5>
								<p>Whole tree, every call.</p>
								<span class="check"></span>
							</div>
						</div>
					</div>

					<div class="row-flex">
						<div class="info">
							<h4>Always show plan before building</h4>
							<p>Every prompt opens Plan Mode first; you approve the SPEC.md before the swarm spins up.</p>
						</div>
						<span class="toggle on" data-tog></span>
					</div>
					<div class="row-flex">
						<div class="info">
							<h4>Auto-approve trivial diffs</h4>
							<p>Skip review when the only change is type-only or styling. Saves ~30s per round-trip.</p>
						</div>
						<span class="toggle" data-tog></span>
					</div>
					<div class="row-flex">
						<div class="info">
							<h4>Stream agent reasoning</h4>
							<p>Show internal thinking blocks in the agent detail panel. Slower to render on large swarms.</p>
						</div>
						<span class="toggle on" data-tog></span>
					</div>
					<div class="row-flex">
						<div class="info">
							<h4>Sound on completion</h4>
							<p>Soft chime when a build finishes or an agent needs your input.</p>
							<div class="meta"><span>FOLEY · CHORUS-1</span><span>−4 LUFS</span></div>
						</div>
						<span class="toggle on" data-tog></span>
					</div>
				</div>
			</div>

			<!-- SECTION: Models -->
			<div class="section">
				<header>
					<div>
						<h3>Model &amp; tokens</h3>
						<p>This month's MiniMax M2.7 budget.</p>
					</div>
					<a href="/pricing" class="btn btn-ghost btn-sm">Change plan</a>
				</header>
				<div class="body">
					<div class="row">
						<div class="label-col">
							<h4>Token quota</h4>
							<p>Resets at 00:00 UTC on the 10th of every month. Soft-throttle warns at 90%.</p>
						</div>
						<div class="quota">
							<div class="top">
								<span class="l">USED &middot; MAY '26</span>
								<span class="v">3.04<em>M</em> <span style="font-family: var(--font-mono); font-size: 11px; color: var(--ink-4); letter-spacing: 0.08em;">/ 8.0M</span></span>
							</div>
							<div class="bar"><div class="fill"></div></div>
							<div class="meta">
								<span>38% USED</span>
								<span>RESETS IN 19 DAYS</span>
							</div>
						</div>
					</div>

					<div class="row">
						<div class="label-col">
							<h4>Primary model</h4>
							<p>The model that powers the root planner. Workers inherit unless overridden per-agent.</p>
						</div>
						<div class="segment">
							<button class="on">M2.7 · Mesh</button>
							<button>M2.5 · Fast</button>
							<button>BYO</button>
						</div>
					</div>

					<div class="plan-card">
						<div>
							<span class="tag">CURRENT PLAN</span>
							<h3>Studio</h3>
							<p>$32 / month · 6 parallel agents · 8M tokens · billed monthly</p>
						</div>
						<a href="/pricing" class="btn btn-luminous btn-sm">Upgrade to Swarm</a>
					</div>
				</div>
			</div>

			<!-- SECTION: Danger -->
			<div class="section">
				<header>
					<div>
						<h3>Danger zone</h3>
						<p>Irreversible. Read twice, click once.</p>
					</div>
				</header>
				<div class="body" style="padding: 18px 22px;">
					<div class="danger">
						<div class="info">
							<h4>Clear local history</h4>
							<p>Removes cached chats and project IDs from this browser. Your projects on the server are untouched.</p>
						</div>
						<button>Clear cache</button>
					</div>
					<div class="danger">
						<div class="info">
							<h4>Reset all settings</h4>
							<p>Restores every preference on this page to factory defaults. Doesn't affect projects, billing, or team members.</p>
						</div>
						<button>Reset</button>
					</div>
					<div class="danger">
						<div class="info">
							<h4>Delete account</h4>
							<p>Permanently removes the swarm, every checkpoint, and every team membership. Cannot be undone after 7 days.</p>
						</div>
						<button>Delete account</button>
					</div>
				</div>
			</div>

			<div class="save-bar">
				<span class="l"><span class="dot"></span>Unsaved changes &middot; <span style="font-family: var(--font-mono); font-size: 11px; color: rgba(255,255,255,0.5); letter-spacing: 0.10em;">3 EDITS</span></span>
				<div class="actions">
					<button>Discard</button>
					<button class="primary">Save changes</button>
				</div>
			</div>

		</div>
	</main>

</div>

<script lang="ts">
	import { onMount } from 'svelte';
	onMount(() => {
		// toggle pills
		document.querySelectorAll('[data-tog]').forEach(el => {
			el.addEventListener('click', () => el.classList.toggle('on'));
		});
		// segment groups
		document.querySelectorAll('.segment').forEach(seg => {
			seg.querySelectorAll('button').forEach(b => {
				b.addEventListener('click', () => {
					seg.querySelectorAll('button').forEach(x => x.classList.remove('on'));
					b.classList.add('on');
				});
			});
		});
		// theme picker
		document.querySelectorAll('.theme').forEach(t => {
			t.addEventListener('click', () => {
				document.querySelectorAll('.theme').forEach(x => x.classList.remove('on'));
				t.classList.add('on');
			});
		});
		// accent picker
		document.querySelectorAll('.accent').forEach(a => {
			a.addEventListener('click', () => {
				document.querySelectorAll('.accent').forEach(x => x.classList.remove('on'));
				a.classList.add('on');
			});
		});
		// ctx cards
		document.querySelectorAll('.ctx').forEach(c => {
			c.addEventListener('click', () => {
				document.querySelectorAll('.ctx').forEach(x => x.classList.remove('on'));
				c.classList.add('on');
			});
		});
		// sidebar nav (visual only — content is appearance for this mock)
		const titles: Record<string, [string, string]> = {
			appearance: ['Appearance', 'Personalize how Chorus renders the mesh, the chat, and every code surface in between.'],
			account:    ['Account', 'Your profile, email, and personal preferences.'],
			swarm:      ['Swarm & agents', 'Tune individual agent personalities, retry budgets, and tool access.'],
			billing:    ['Billing', 'Invoices, payment method, and seat allocation.'],
			integrations:['Integrations', 'GitHub, Slack, MCP servers, and outbound webhooks.'],
			security:   ['Security', 'SSO, MFA, session policy, and IP allow-list.'],
			advanced:   ['Advanced', 'Power-user toggles, beta features, and the export panel.'],
		};
		document.querySelectorAll('.nav-item').forEach(n => {
			n.addEventListener('click', () => {
				document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active'));
				n.classList.add('active');
				const t = titles[n.getAttribute('data-tab') || ''] || ['Appearance', ''];
				const pageTitle = document.getElementById('pageTitle');
				const pageLede = document.getElementById('pageLede');
				const crumbCur = document.getElementById('crumbCur');
				if (pageTitle) pageTitle.textContent = t[0];
				if (pageLede) pageLede.textContent = t[1];
				if (crumbCur) crumbCur.textContent = t[0].toUpperCase();
			});
		});
	});
</script>
