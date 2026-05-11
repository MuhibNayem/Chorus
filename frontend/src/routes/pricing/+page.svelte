<svelte:head>
	<title>Pricing — Chorus</title>
	<style>
		body { background: var(--paper-0); }
		.page-head {
			position: relative;
			padding: 140px 32px 48px;
			text-align: center;
			overflow: hidden;
			isolation: isolate;
		}
		.page-head::before {
			content: ""; position: absolute; inset: -10%;
			background:
				radial-gradient(40% 40% at 30% 0%, oklch(85% 0.10 295 / 0.45), transparent 60%),
				radial-gradient(40% 40% at 70% 0%, oklch(88% 0.09 220 / 0.40), transparent 60%);
			z-index: -1;
		}
		.page-head h1 {
			font-family: var(--font-display);
			font-weight: 400;
			font-size: clamp(56px, 8vw, 112px);
			line-height: 0.95; letter-spacing: -0.025em;
			margin: 18px 0 24px;
		}
		.page-head h1 em { font-style: italic; color: var(--violet-d); }
		.page-head .lede { margin: 0 auto; }

		/* Billing toggle */
		.toggle {
			margin: 32px auto 0;
			display: inline-flex; align-items: center;
			padding: 5px;
			background: var(--paper-1);
			border: 1px solid var(--line);
			border-radius: 999px;
			box-shadow: var(--shadow-1);
			gap: 0;
		}
		.toggle button {
			border: 0; background: transparent;
			padding: 9px 22px;
			border-radius: 999px;
			font-size: 13px; font-weight: 500;
			color: var(--ink-4);
			transition: all 200ms ease;
			display: inline-flex; align-items: center; gap: 8px;
		}
		.toggle button.on {
			background: var(--ink-0);
			color: var(--paper-0);
			box-shadow: 0 4px 14px rgba(20,18,32,0.18);
		}
		.toggle button .save {
			font-family: var(--font-mono); font-size: 10px;
			background: var(--violet); color: white;
			padding: 2px 7px; border-radius: 999px;
			letter-spacing: 0.06em;
		}

		/* Plans grid */
		.plans {
			max-width: 1240px; margin: 56px auto 0;
			padding: 0 32px;
			display: grid;
			grid-template-columns: repeat(4, 1fr);
			gap: 12px;
		}
		@media (max-width: 1100px) { .plans { grid-template-columns: repeat(2, 1fr); } }
		@media (max-width: 640px)  { .plans { grid-template-columns: 1fr; } }
		.plan {
			background: var(--paper-0);
			border: 1px solid var(--line);
			border-radius: 24px;
			padding: 28px;
			display: flex; flex-direction: column; gap: 16px;
			position: relative;
		}
		.plan.feat-tier {
			background: var(--ink-0);
			color: white;
			border-color: var(--ink-0);
			box-shadow: 0 24px 60px rgba(20, 18, 32, 0.20), 0 0 0 1px rgba(167, 139, 250, 0.30), 0 0 80px rgba(167, 139, 250, 0.20);
			transform: translateY(-8px);
		}
		.plan.feat-tier::before {
			content: ""; position: absolute; inset: 0;
			border-radius: 24px;
			background: linear-gradient(180deg, oklch(70% 0.18 295 / 0.18), transparent 50%);
			pointer-events: none;
		}
		.plan .badge-pop {
			position: absolute; top: -12px; left: 50%;
			transform: translateX(-50%);
			background: var(--violet);
			color: white;
			font-family: var(--font-mono); font-size: 10px;
			letter-spacing: 0.14em; text-transform: uppercase;
			padding: 5px 12px; border-radius: 999px;
			box-shadow: 0 8px 20px rgba(124, 58, 237, 0.4);
		}
		.plan .tier {
			font-family: var(--font-mono); font-size: 11px;
			letter-spacing: 0.16em; text-transform: uppercase;
			color: var(--ink-5);
		}
		.plan.feat-tier .tier { color: var(--violet-2); }
		.plan h3 { font-size: 22px; font-weight: 500; letter-spacing: -0.015em; margin: 0; }
		.plan .price-row {
			display: flex; align-items: baseline; gap: 6px;
			border-bottom: 1px dashed var(--line); padding-bottom: 18px;
		}
		.plan.feat-tier .price-row { border-bottom-color: rgba(255,255,255,0.10); }
		.plan .amt {
			font-family: var(--font-display);
			font-size: 60px; line-height: 1;
			letter-spacing: -0.02em;
		}
		.plan .per { font-size: 13px; color: var(--ink-5); }
		.plan.feat-tier .per { color: rgba(255,255,255,0.55); }
		.plan .desc { font-size: 13.5px; color: var(--ink-4); margin: 0; line-height: 1.5; }
		.plan.feat-tier .desc { color: rgba(255,255,255,0.72); }
		.plan ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; font-size: 13.5px; }
		.plan li { display: flex; gap: 10px; align-items: flex-start; color: var(--ink-2); }
		.plan li svg { flex-shrink: 0; margin-top: 2px; color: var(--violet-d);}
		.plan.feat-tier li { color: rgba(255,255,255,0.85); }
		.plan.feat-tier li svg { color: var(--violet-2); }
		.plan li.muted { color: var(--ink-5); }
		.plan li.muted svg { color: var(--line-strong); }
		.plan .cta-row { margin-top: auto; display: grid; gap: 8px; }

		/* Comparison table */
		.compare-section {
			padding: 80px 32px 60px;
			max-width: 1240px; margin: 0 auto;
		}
		.compare-section h2 { margin-bottom: 32px; }
		.compare-wrap {
			border: 1px solid var(--line);
			border-radius: 24px;
			overflow: hidden;
			background: var(--paper-0);
		}
		table.compare {
			width: 100%; border-collapse: collapse;
			font-size: 13.5px;
		}
		table.compare thead th {
			background: var(--paper-1);
			text-align: left;
			padding: 18px 20px;
			font-family: var(--font-mono);
			font-size: 11px; letter-spacing: 0.14em;
			text-transform: uppercase;
			color: var(--ink-4);
			font-weight: 500;
			border-bottom: 1px solid var(--line);
		}
		table.compare thead th.feat {
			background: var(--ink-0); color: white;
		}
		table.compare th.row-h {
			text-align: left; padding: 16px 20px;
			color: var(--ink-1); font-weight: 500;
			background: var(--paper-1);
			border-right: 1px solid var(--line);
			width: 32%;
		}
		table.compare td {
			padding: 16px 20px;
			border-bottom: 1px solid var(--line);
			color: var(--ink-2);
		}
		table.compare td.feat-cell { background: oklch(98% 0.012 295); color: var(--ink-1); font-weight: 500;}
		table.compare tbody tr:last-child td, table.compare tbody tr:last-child th { border-bottom: 0; }
		table.compare .check svg { color: var(--violet-d); }
		table.compare td.feat-cell .check svg { color: var(--violet-d); }
		table.compare .group-row th {
			font-family: var(--font-mono); font-size: 11px;
			letter-spacing: 0.14em; text-transform: uppercase;
			color: var(--ink-5); padding-top: 24px; padding-bottom: 12px;
			background: var(--paper-0); font-weight: 500;
		}

		/* FAQ */
		.faq { padding: 60px 32px 120px; max-width: 920px; margin: 0 auto; }
		.faq h2 { margin-bottom: 32px; }
		.qa {
			border: 1px solid var(--line);
			border-radius: 18px;
			margin-bottom: 10px;
			background: var(--paper-0);
			transition: border 200ms ease;
		}
		.qa[open] { border-color: var(--line-strong); }
		.qa summary {
			list-style: none;
			padding: 20px 24px;
			cursor: pointer;
			display: flex; align-items: center; justify-content: space-between;
			font-size: 16px; font-weight: 500;
			letter-spacing: -0.01em;
		}
		.qa summary::-webkit-details-marker { display: none; }
		.qa summary::after {
			content: "+";
			font-size: 22px; color: var(--ink-4);
			transition: transform 220ms ease;
			font-weight: 300;
		}
		.qa[open] summary::after { content: "−"; }
		.qa .a {
			padding: 0 24px 24px;
			color: var(--ink-4); font-size: 14.5px; line-height: 1.6;
		}

		/* CTA */
		.pricing-cta {
			margin: 40px 32px 80px;
			max-width: 1240px;
			margin-left: auto; margin-right: auto;
			border-radius: 28px;
			padding: 56px;
			background: var(--ink-0); color: white;
			display: grid; grid-template-columns: 1.2fr 0.8fr;
			gap: 32px; align-items: center;
			position: relative; overflow: hidden;
		}
		.pricing-cta h3 {
			font-family: var(--font-display);
			font-weight: 400;
			font-size: clamp(32px, 4vw, 48px);
			line-height: 1; letter-spacing: -0.02em;
			margin: 0; color: white;
		}
		.pricing-cta p { color: rgba(255,255,255,0.65); margin: 12px 0 0; max-width: 50ch; font-size: 15px; }
		.pricing-cta .actions { display: flex; flex-direction: column; gap: 10px; }
		@media (max-width: 880px) { .pricing-cta { grid-template-columns: 1fr; padding: 36px; } }
	</style>
</svelte:head>

<nav class="nav" data-screen-label="Pricing — Nav">
	<a href="/" class="nav-brand">
		<span class="hex-mark"><svg viewBox="0 0 32 32" fill="none">
			<path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z" fill="url(#g1)" stroke="rgba(0,0,0,0.1)" stroke-width="1"/>
			<path d="M16 9 L22 12.5 L22 19.5 L16 23 L10 19.5 L10 12.5 Z" fill="white"/>
			<defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs>
		</svg></span>
		Chorus
	</a>
	<div class="nav-links">
		<a href="/" class="nav-link">Product</a>
		<a href="/pricing" class="nav-link active">Pricing</a>
		<a href="/#how" class="nav-link">How it works</a>
		<a href="#" class="nav-link">Docs</a>
		<a href="#" class="nav-link">Blog</a>
	</div>
	<a href="/login" class="nav-link">Sign in</a>
	<a href="/register" class="btn btn-luminous btn-sm nav-cta">Start free</a>
</nav>

<section class="page-head" data-screen-label="Pricing — Head">
	<span class="eyebrow">Pricing · 2026</span>
	<h1>Pay per <em>parallel agent</em>,<br/>not per token.</h1>
	<p class="lede" style="margin-left:auto; margin-right:auto;">Every plan ships with the full mesh, plan mode, time-travel checkpoints, and sandbox execution. Higher tiers unlock more concurrent agents and team controls.</p>
	<div class="toggle">
		<button class="on" id="t-mo">Monthly</button>
		<button id="t-yr">Annual <span class="save">−20%</span></button>
	</div>
</section>

<div class="plans" data-screen-label="Pricing — Plans">
	<article class="plan">
		<span class="tier">01 / Solo</span>
		<h3>For tinkering</h3>
		<div class="price-row">
			<span class="amt" data-mo="$0" data-yr="$0">$0</span>
			<span class="per">/forever</span>
		</div>
		<p class="desc">Hobby builds, learning the swarm, demoing to the team.</p>
		<ul>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>3 active projects</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>2 parallel agents</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>ZIP + local sandbox</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Community Discord</li>
			<li class="muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg>No GitHub push</li>
		</ul>
		<div class="cta-row">
			<a href="/register" class="btn btn-ghost">Start free</a>
		</div>
	</article>

	<article class="plan feat-tier">
		<span class="badge-pop">Most popular</span>
		<span class="tier">02 / Studio</span>
		<h3>For solo builders</h3>
		<div class="price-row">
			<span class="amt" data-mo="$32" data-yr="$26">$32</span>
			<span class="per">/month</span>
		</div>
		<p class="desc">Ship real products. The plan most Chorus users land on.</p>
		<ul>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Unlimited projects</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>6 parallel agents</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Docker images + GitHub push</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Time-travel checkpoints</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Priority MiniMax tokens</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Plan Mode + diagrams</li>
		</ul>
		<div class="cta-row">
			<a href="/register" class="btn btn-luminous">Start 14-day trial</a>
			<a href="/register" class="btn btn-on-dark-ghost btn-sm" style="justify-content:center;">No card required</a>
		</div>
	</article>

	<article class="plan">
		<span class="tier">03 / Swarm</span>
		<h3>For teams</h3>
		<div class="price-row">
			<span class="amt" data-mo="$120" data-yr="$96">$120</span>
			<span class="per">/seat /month</span>
		</div>
		<p class="desc">Multi-swarm, team controls, audit trails.</p>
		<ul>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Everything in Studio</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>16 parallel agents</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>SAML SSO + role policies</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Audit log · 1-year retention</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Shared blackboard across team</li>
		</ul>
		<div class="cta-row">
			<a href="/register" class="btn btn-primary">Start team trial</a>
		</div>
	</article>

	<article class="plan">
		<span class="tier">04 / Enterprise</span>
		<h3>For platforms</h3>
		<div class="price-row">
			<span class="amt" style="font-size:48px;">Custom</span>
		</div>
		<p class="desc">Self-hosted swarm, BYO LLM, custom agents, dedicated CSM.</p>
		<ul>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Self-hosted sandbox cluster</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>BYO LLM (MiniMax / open weights)</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Custom agent SDK</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>SOC 2 + DPA + InfoSec review</li>
			<li><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>99.95% SLA · 24/7 on-call</li>
		</ul>
		<div class="cta-row">
			<a href="#" class="btn btn-ghost">Talk to sales</a>
		</div>
	</article>
</div>

<section class="compare-section" data-screen-label="Pricing — Compare">
	<div style="display:flex; align-items: end; justify-content: space-between; gap: 32px; flex-wrap: wrap;">
		<div>
			<span class="eyebrow">A ── Compare</span>
			<h2 class="h-section" style="margin-top: 16px;">Every feature,<br/>every plan.</h2>
		</div>
		<p style="max-width: 36ch; color: var(--ink-4); margin: 0;">Annual prices apply across all paid tiers. Switch any time — we prorate to the day.</p>
	</div>

	<div class="compare-wrap" style="margin-top: 32px;">
		<table class="compare">
			<thead>
				<tr>
					<th class="row-h" style="background: var(--ink-0); color: white;">Feature</th>
					<th>Solo</th>
					<th class="feat">Studio</th>
					<th>Swarm</th>
					<th>Enterprise</th>
				</tr>
			</thead>
			<tbody>
				<tr class="group-row"><th colspan="5">Swarm capacity</th></tr>
				<tr><th class="row-h">Active projects</th><td>3</td><td class="feat-cell">Unlimited</td><td>Unlimited</td><td>Unlimited</td></tr>
				<tr><th class="row-h">Parallel agents</th><td>2</td><td class="feat-cell">6</td><td>16</td><td>Custom</td></tr>
				<tr><th class="row-h">Multi-swarm orchestration</th><td>—</td><td class="feat-cell">—</td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>
				<tr><th class="row-h">Context window per agent</th><td>32k</td><td class="feat-cell">196k</td><td>196k</td><td>Custom</td></tr>

				<tr class="group-row"><th colspan="5">Output</th></tr>
				<tr><th class="row-h">ZIP archive</th><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td class="feat-cell"><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>
				<tr><th class="row-h">Docker image build</th><td>—</td><td class="feat-cell"><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>
				<tr><th class="row-h">GitHub push</th><td>—</td><td class="feat-cell"><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>

				<tr class="group-row"><th colspan="5">Collaboration</th></tr>
				<tr><th class="row-h">Team seats</th><td>1</td><td class="feat-cell">1</td><td>Up to 25</td><td>Unlimited</td></tr>
				<tr><th class="row-h">SAML SSO</th><td>—</td><td class="feat-cell">—</td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>
				<tr><th class="row-h">Audit log</th><td>—</td><td class="feat-cell">7 days</td><td>1 year</td><td>Indefinite</td></tr>

				<tr class="group-row"><th colspan="5">Sandbox & security</th></tr>
				<tr><th class="row-h">Local sandbox (Seatbelt / bubblewrap)</th><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td class="feat-cell"><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>
				<tr><th class="row-h">Self-hosted sandbox</th><td>—</td><td class="feat-cell">—</td><td>Add-on</td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>
				<tr><th class="row-h">SOC 2 Type II</th><td>—</td><td class="feat-cell">—</td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td><td><span class="check"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span></td></tr>

				<tr class="group-row"><th colspan="5">Support</th></tr>
				<tr><th class="row-h">Channel</th><td>Community</td><td class="feat-cell">Email · 24h</td><td>Slack · 4h</td><td>Dedicated CSM</td></tr>
				<tr><th class="row-h">SLA</th><td>—</td><td class="feat-cell">99.5%</td><td>99.9%</td><td>99.95%</td></tr>
			</tbody>
		</table>
	</div>
</section>

<section class="faq" data-screen-label="Pricing — FAQ">
	<span class="eyebrow">B ── Common questions</span>
	<h2 class="h-section" style="margin-top: 16px; margin-bottom: 32px;">Asked & answered.</h2>

	<details class="qa" open>
		<summary>What counts as a "parallel agent"?</summary>
		<div class="a">An agent is a peer in the swarm with its own context window, tool set, and task queue. Parallelism is the cap on simultaneously-running agents per project. Solo runs root + one worker; Studio runs the full mesh; Swarm scales beyond the default agent set.</div>
	</details>
	<details class="qa">
		<summary>How is a project counted toward my limit?</summary>
		<div class="a">Active projects are ones with a workspace and chat history. Archive a project at any time to free a slot — your code, checkpoints, and ZIP exports remain accessible.</div>
	</details>
	<details class="qa">
		<summary>Are MiniMax tokens included?</summary>
		<div class="a">Yes — every plan ships with a generous monthly token allotment. Studio includes 8M tokens, Swarm 32M per seat, Enterprise unlimited or BYO. We never throttle mid-build.</div>
	</details>
	<details class="qa">
		<summary>Can I bring my own LLM?</summary>
		<div class="a">On Enterprise, yes. Point Chorus at any OpenAI-compatible endpoint or self-hosted MiniMax / open-weight model. Studio and Swarm currently use the managed MiniMax M2.7 fleet.</div>
	</details>
	<details class="qa">
		<summary>What happens to my projects if I downgrade?</summary>
		<div class="a">Existing projects stay readable forever. If you exceed the new tier's active-project limit, the oldest projects auto-archive — you can promote them back any time.</div>
	</details>
	<details class="qa">
		<summary>Do you offer discounts for students or open source?</summary>
		<div class="a">Yes. Verified students and maintainers of public OSS projects get Studio free of charge. Drop a note from your .edu address or link a maintained repo.</div>
	</details>
</section>

<div class="pricing-cta" data-screen-label="Pricing — CTA">
	<div>
		<span class="eyebrow on-dark">Still deciding?</span>
		<h3 style="margin-top: 12px;">Spin up a free build right now. Decide later.</h3>
		<p>Two-minute signup. No card. Your first project is on us — every plan starts with a fully functional swarm.</p>
	</div>
	<div class="actions">
		<a href="/register" class="btn btn-luminous btn-lg" style="justify-content:center;">Start free</a>
		<a href="#" class="btn btn-on-dark-ghost" style="justify-content:center;">Book a demo</a>
	</div>
</div>

<footer style="background: var(--paper-1);">
	<div class="container">
		<div class="footer">
			<div>
				<div style="display:flex; align-items:center; gap:10px; color: var(--ink-1); font-weight:600; font-size:16px;">
					<span class="hex-mark"><svg viewBox="0 0 32 32" fill="none">
						<path d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z" fill="url(#g3)" stroke="rgba(0,0,0,0.1)" stroke-width="1"/>
						<path d="M16 9 L22 12.5 L22 19.5 L16 23 L10 19.5 L10 12.5 Z" fill="white"/>
						<defs><linearGradient id="g3" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs>
					</svg></span>Chorus
				</div>
				<p style="margin: 16px 0 0; max-width: 36ch; font-size: 13px;">Decentralized AI agent swarm for production code generation.</p>
			</div>
			<div><h5>Product</h5><ul><li><a href="/">Overview</a></li><li><a href="/pricing">Pricing</a></li><li><a href="#">Changelog</a></li></ul></div>
			<div><h5>Resources</h5><ul><li><a href="#">Documentation</a></li><li><a href="#">Templates</a></li><li><a href="#">Status</a></li></ul></div>
			<div><h5>Company</h5><ul><li><a href="#">About</a></li><li><a href="#">Blog</a></li><li><a href="#">Careers</a></li></ul></div>
		</div>
		<div style="display: flex; justify-content: space-between; padding: 24px 32px 48px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.06em; color: var(--ink-5); border-top: 1px solid var(--line); margin-top: 24px;">
			<span>© 2026 Chorus Labs</span>
			<span>v2.0.4 · ALL SYSTEMS NOMINAL</span>
		</div>
	</div>
</footer>

<script lang="ts">
	import { onMount } from 'svelte';
	onMount(() => {
		const tMo = document.getElementById('t-mo');
		const tYr = document.getElementById('t-yr');
		function setBilling(yr: boolean) {
			tMo?.classList.toggle('on', !yr);
			tYr?.classList.toggle('on', yr);
			document.querySelectorAll<HTMLElement>('.amt[data-mo]').forEach(el => {
				el.textContent = yr ? (el.dataset.yr ?? '') : (el.dataset.mo ?? '');
			});
		}
		tMo?.addEventListener('click', () => setBilling(false));
		tYr?.addEventListener('click', () => setBilling(true));
	});
</script>
