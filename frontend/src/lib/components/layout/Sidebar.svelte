<script lang="ts">
	import { page } from '$app/state';
	import { Activity, Network, Microscope, PlayCircle, Shield } from 'lucide-svelte';

	const navItems = [
		{ label: 'Rule Health', href: '/', icon: Activity },
		{ label: 'Graph Search', href: '/graph-search', icon: Network },
		{ label: 'Rule Analyzer', href: '/rule-analyzer', icon: Microscope },
		{ label: 'Rule Simulator', href: '/rule-simulator', icon: PlayCircle }
	];
</script>

<aside class="sidebar">
	<div class="brand">
		<Shield size={20} strokeWidth={2} color="var(--accent)" />
		<span class="brand-name">Rule Intelligence</span>
	</div>

	<nav>
		{#each navItems as item (item.href)}
			{@const isActive = page.url.pathname === item.href}
			<a href={item.href} class="nav-item" class:active={isActive}>
				<item.icon size={18} strokeWidth={2} />
				<span>{item.label}</span>
			</a>
		{/each}
	</nav>
</aside>

<style>
	.sidebar {
		width: 240px;
		flex-shrink: 0;
		background: var(--bg-sidebar);
		border-right: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		height: 100vh;
		position: sticky;
		top: 0;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 1.25rem 1.25rem;
		border-bottom: 1px solid var(--border);
	}

	.brand-name {
		font-weight: 600;
		font-size: 0.95rem;
		letter-spacing: -0.01em;
	}

	nav {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding: 0.75rem;
	}

	.nav-item {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 0.55rem 0.75rem;
		border-radius: var(--radius);
		text-decoration: none;
		color: var(--text-muted);
		font-size: 0.875rem;
		font-weight: 500;
		transition:
			background 0.12s ease,
			color 0.12s ease;
	}

	.nav-item:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.nav-item.active {
		background: var(--accent-dim);
		color: var(--accent);
	}
</style>