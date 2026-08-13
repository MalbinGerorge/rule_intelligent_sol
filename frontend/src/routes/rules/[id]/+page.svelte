<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { fetchRuleGraph } from '$lib/api/graph';
	import { ApiError } from '$lib/api/client';
	import type { RuleGraphDetail } from '$lib/types/graph';

	let detail = $state<RuleGraphDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			detail = await fetchRuleGraph(Number(page.params.id));
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to load rule';
		} finally {
			loading = false;
		}
	});
</script>

{#if loading}
	<div class="empty-state">Loading…</div>
{:else if error}
	<div class="empty-state error">{error}</div>
{:else if detail}
	<div class="header">
		<div class="title-row">
			<h1>{detail.rule.name}</h1>
			<span class="badge" class:enabled={detail.rule.enabled} class:disabled={!detail.rule.enabled}>
				{detail.rule.enabled ? 'Enabled' : 'Disabled'}
			</span>
			<span class="badge type">{detail.rule.object_type}</span>
		</div>
		<p class="subtitle mono">{detail.rule.identifier}</p>
	</div>

	<div class="grid">
		<section class="panel">
			<h2>Conditions</h2>
			{#if detail.conditions.length === 0}
				<p class="muted">No standalone conditions — logic is entirely composed via referenced building blocks below.</p>
			{:else}
				<ul class="condition-list">
					{#each detail.conditions as c, i (i)}
						<li class:negated={c.negated}>
							{#if c.negated}<span class="not-tag">NOT</span>{/if}
							{c.raw_text ?? c.test_class}
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section class="panel">
			<h2>References</h2>
			{#if detail.references.length === 0}
				<p class="muted">Doesn't reference any building blocks.</p>
			{:else}
				<ul class="ref-list">
					{#each detail.references as r (r.identifier)}
						<li>
							<a href="/graph-search">{r.name}</a>
							{#if r.threshold?.threshold_count}
								<span class="threshold-tag">
									{r.threshold.threshold_count}× / {r.threshold.threshold_time_value}{r.threshold
										.threshold_time_unit}
								</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section class="panel">
			<h2>Requires</h2>
			{#if detail.log_sources.length === 0}
				<p class="muted">No log source requirement.</p>
			{:else}
				<ul class="chip-list">
					{#each detail.log_sources as ls (ls)}
						<li class="chip">{ls}</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section class="panel">
			<h2>MITRE ATT&CK</h2>
			{#if detail.mitre.length === 0}
				<p class="muted">No technique mapped.</p>
			{:else}
				<ul class="mitre-list">
					{#each detail.mitre as m (m.technique_id)}
						<li>
							<span class="mono">{m.technique_id}</span> — {m.technique_name}
							{#if m.tactic_name}<span class="muted"> · {m.tactic_name}</span>{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		{#if detail.followed_by.length > 0}
			<section class="panel wide">
				<h2>Sequence relationships this rule defines</h2>
				<ul class="sequence-list">
					{#each detail.followed_by as f, i (i)}
						<li>
							{f.source_name} <span class="arrow">→</span> {f.target_name}
							{#if f.relationship?.time_value}
								<span class="muted"> · within {f.relationship.time_value} {f.relationship.time_unit}</span>
							{/if}
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	</div>
{/if}

<style>
	.header {
		margin-bottom: 1.5rem;
	}
	.title-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	h1 {
		font-size: 1.3rem;
		margin: 0;
	}
	.subtitle {
		color: var(--text-muted);
		margin: 0.35rem 0 0;
		font-size: 0.85rem;
	}
	.badge {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0.2rem 0.55rem;
		border-radius: 999px;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.badge.enabled {
		background: var(--accent-dim);
		color: var(--accent);
	}
	.badge.disabled {
		background: var(--warning-dim);
		color: var(--warning);
	}
	.badge.type {
		background: var(--surface-hover);
		color: var(--text-muted);
	}

	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}
	.panel {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1rem 1.1rem;
	}
	.panel.wide {
		grid-column: 1 / -1;
	}
	h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-faint);
		margin: 0 0 0.75rem;
	}

	.condition-list,
	.ref-list,
	.mitre-list,
	.sequence-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.condition-list li {
		font-size: 0.85rem;
		line-height: 1.4;
		padding: 0.5rem 0.6rem;
		background: var(--bg);
		border-radius: 6px;
		border-left: 2px solid var(--accent);
	}
	.condition-list li.negated {
		border-left-color: var(--warning);
	}
	.not-tag {
		font-size: 0.65rem;
		font-weight: 700;
		color: var(--warning);
		margin-right: 0.4rem;
	}

	.ref-list li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-size: 0.875rem;
	}
	.threshold-tag {
		font-family: 'IBM Plex Mono', ui-monospace, monospace;
		font-size: 0.75rem;
		color: var(--accent);
		background: var(--accent-dim);
		padding: 0.15rem 0.5rem;
		border-radius: 6px;
	}

	.chip-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.chip {
		font-size: 0.8rem;
		padding: 0.3rem 0.65rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 999px;
	}

	.mitre-list li {
		font-size: 0.875rem;
	}

	.sequence-list li {
		font-size: 0.875rem;
		padding: 0.4rem 0;
	}
	.arrow {
		color: var(--accent);
	}

	.mono {
		font-family: 'IBM Plex Mono', ui-monospace, monospace;
	}
	.muted {
		color: var(--text-muted);
		font-size: 0.85rem;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
		color: var(--text-muted);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
	}
	.empty-state.error {
		color: var(--warning);
	}
</style>