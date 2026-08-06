<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchHealthMetrics } from '$lib/api/rules';
	import { ApiError } from '$lib/api/client';
	import type { RuleHealthMetrics } from '$lib/types/rule';
	import MetricCard from '$lib/components/dashboard/MetricCard.svelte';

	let metrics = $state<RuleHealthMetrics | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// TODO: replace with a real customer selector once there's more than one
	const CUSTOMER_ID = 1;

	onMount(async () => {
		try {
			metrics = await fetchHealthMetrics(CUSTOMER_ID);
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to load metrics';
		} finally {
			loading = false;
		}
	});
</script>

<div class="header">
	<h1>Rule Health</h1>
	<p class="subtitle">Detection coverage and rule status at a glance.</p>
</div>

{#if loading}
	<p class="state">Loading metrics…</p>
{:else if error}
	<p class="state error">{error}</p>
{:else if metrics}
	<div class="grid">
		<MetricCard label="Total Rules" value={metrics.total_rules} tone="neutral" />
		<MetricCard label="Building Blocks" value={metrics.total_building_blocks} tone="neutral" />
		<MetricCard label="Enabled" value={metrics.enabled_rules} tone="accent" />
		<MetricCard label="Disabled" value={metrics.disabled_rules} tone="warning" />
		<MetricCard
			label="Enabled — Triggered"
			value={metrics.enabled_triggered}
			tone="accent"
			hint="Has fired at least once"
		/>
		<MetricCard
			label="Enabled — Never Triggered"
			value={metrics.enabled_not_triggered}
			tone="warning"
			hint="No activity recorded"
		/>
	</div>
{/if}

<style>
	.header {
		margin-bottom: 1.5rem;
	}

	h1 {
		font-size: 1.4rem;
		font-weight: 600;
		margin: 0 0 0.3rem 0;
		letter-spacing: -0.01em;
	}

	.subtitle {
		color: var(--text-muted);
		font-size: 0.9rem;
		margin: 0;
	}

	.state {
		color: var(--text-muted);
		font-size: 0.9rem;
	}

	.state.error {
		color: var(--warning);
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 1rem;
	}

	@media (max-width: 900px) {
		.grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}

	@media (max-width: 600px) {
		.grid {
			grid-template-columns: 1fr;
		}
	}
</style>