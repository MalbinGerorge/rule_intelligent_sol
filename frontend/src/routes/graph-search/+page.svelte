<script lang="ts">
	import { searchByField, fetchBbDependents } from '$lib/api/graph';
	import { ApiError } from '$lib/api/client';
	import type { FieldSearchResult, BuildingBlockDependent } from '$lib/types/graph';
	import { Search, GitBranch } from 'lucide-svelte';

	// TODO: replace with a real customer selector once there's more than one
	const CUSTOMER_ID = 1;

	let mode = $state<'field' | 'dependents'>('dependents');
	let query = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);
	let fieldResults = $state<FieldSearchResult[]>([]);
	let dependentResults = $state<BuildingBlockDependent[]>([]);
	let searched = $state(false);

	async function runSearch() {
		if (!query.trim()) return;
		loading = true;
		error = null;
		searched = true;
		try {
			if (mode === 'field') {
				fieldResults = await searchByField(query.trim(), CUSTOMER_ID);
			} else {
				dependentResults = await fetchBbDependents(query.trim(), CUSTOMER_ID);
			}
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Search failed';
			fieldResults = [];
			dependentResults = [];
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') runSearch();
	}
</script>

<div class="header">
	<h1>Graph Search</h1>
	<p class="subtitle">Trace what a rule depends on, and what depends back on it.</p>
</div>

<div class="mode-tabs">
	<button class:active={mode === 'dependents'} onclick={() => (mode = 'dependents')}>
		<GitBranch size={16} strokeWidth={2} />
		Blast radius — who depends on this building block?
	</button>
	<button class:active={mode === 'field'} onclick={() => (mode = 'field')}>
		<Search size={16} strokeWidth={2} />
		Field search — which rules check this field?
	</button>
</div>

<div class="search-bar">
	<input
		type="text"
		bind:value={query}
		onkeydown={handleKeydown}
		placeholder={mode === 'dependents'
			? 'Building block identifier, e.g. SYSTEM-1300'
			: 'Event field, e.g. Command'}
	/>
	<button class="search-btn" onclick={runSearch} disabled={loading}>
		{loading ? 'Searching…' : 'Search'}
	</button>
</div>

{#if error}
	<div class="empty-state error">{error}</div>
{:else if loading}
	<div class="empty-state">Searching…</div>
{:else if searched && mode === 'dependents' && dependentResults.length === 0}
	<div class="empty-state">No rules depend on "{query}" — check the identifier is exact.</div>
{:else if searched && mode === 'field' && fieldResults.length === 0}
	<div class="empty-state">No conditions found checking the field "{query}".</div>
{:else if mode === 'dependents' && dependentResults.length > 0}
	<table>
		<thead>
			<tr>
				<th>Rule</th>
				<th>Identifier</th>
				<th>Threshold</th>
			</tr>
		</thead>
		<tbody>
			{#each dependentResults as r (r.rule_id)}
				<tr>
					<td><a href="/rules/{r.rule_id}">{r.name}</a></td>
					<td class="mono muted">{r.identifier}</td>
					<td class="mono">
						{#if r.threshold?.threshold_count}
							{r.threshold.threshold_count}× / {r.threshold.threshold_time_value}{r.threshold
								.threshold_time_unit}
						{:else}
							<span class="muted">plain reference</span>
						{/if}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{:else if mode === 'field' && fieldResults.length > 0}
	<table>
		<thead>
			<tr>
				<th>Rule</th>
				<th>Operator</th>
				<th>Values</th>
			</tr>
		</thead>
		<tbody>
			{#each fieldResults as r (r.rule_id + (r.operator ?? ''))}
				<tr>
					<td><a href="/rules/{r.rule_id}">{r.name}</a></td>
					<td class="muted">{r.operator}</td>
					<td class="mono">{(r.values ?? []).join(', ')}</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	.header {
		margin-bottom: 1.5rem;
	}
	h1 {
		font-size: 1.4rem;
		margin: 0 0 0.25rem;
	}
	.subtitle {
		color: var(--text-muted);
		margin: 0;
		font-size: 0.9rem;
	}

	.mode-tabs {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}
	.mode-tabs button {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text-muted);
		font-size: 0.85rem;
		cursor: pointer;
		transition: border-color 0.12s ease, color 0.12s ease;
	}
	.mode-tabs button.active {
		border-color: var(--accent);
		color: var(--accent);
	}

	.search-bar {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1.5rem;
	}
	.search-bar input {
		flex: 1;
		padding: 0.65rem 0.9rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		font-size: 0.9rem;
	}
	.search-bar input:focus {
		outline: none;
		border-color: var(--accent);
	}
	.search-btn {
		padding: 0.65rem 1.25rem;
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		color: var(--accent);
		font-size: 0.9rem;
		font-weight: 500;
		cursor: pointer;
	}
	.search-btn:disabled {
		opacity: 0.5;
		cursor: default;
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

	table {
		width: 100%;
		border-collapse: collapse;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		overflow: hidden;
	}
	th {
		text-align: left;
		padding: 0.75rem 1rem;
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-faint);
		border-bottom: 1px solid var(--border);
	}
	td {
		padding: 0.65rem 1rem;
		border-bottom: 1px solid var(--border);
		font-size: 0.875rem;
	}
	tr:last-child td {
		border-bottom: none;
	}
	tr:hover td {
		background: var(--surface-hover);
	}
	.mono {
		font-family: 'IBM Plex Mono', ui-monospace, monospace;
		font-size: 0.8rem;
	}
	.muted {
		color: var(--text-muted);
	}
</style>