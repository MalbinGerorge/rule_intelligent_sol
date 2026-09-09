<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchCustomers, type Customer } from '$lib/api/customers';
	import { startSigmaGeneration, fetchMitreGaps, fetchLogSourceGaps } from '$lib/api/recommendations';
	import { selectedCustomerId } from '$lib/stores/customer';
	import { ApiError } from '$lib/api/client';
	import { API_BASE } from '$lib/config/env';
	import type { MitreGap, LogSourceGap, PeerRuleSuggestion } from '$lib/types/recommendations';

	let customers = $state<Customer[]>([]);
	let running = $state(false);
	let processedRules = $state(0);
	let totalRules = $state(0);
	let failedRules = $state(0);
	let status = $state<string | null>(null);
	let error = $state<string | null>(null);
	let eventSource: EventSource | null = null;

	let viewingSuggestion = $state<PeerRuleSuggestion | null>(null);

	function formatAsSigmaYaml(s: PeerRuleSuggestion): string {
		const lines: string[] = [];
		lines.push(`title: ${s.title}`);
		if (s.description) lines.push(`description: ${s.description}`);
		if (s.level) lines.push(`level: ${s.level}`);

		const detection = s.detection as {
			selections?: Record<string, Record<string, unknown>>;
			condition?: string;
		};
		if (detection?.selections) {
			lines.push('detection:');
			for (const [name, fields] of Object.entries(detection.selections)) {
				lines.push(`  ${name}:`);
				for (const [field, value] of Object.entries(fields)) {
					const valStr = Array.isArray(value)
						? `[${value.map((v) => `'${v}'`).join(', ')}]`
						: `'${value}'`;
					lines.push(`    ${field}: ${valStr}`);
				}
			}
			if (detection.condition) lines.push(`  condition: ${detection.condition}`);
		}

		if (s.tags.length > 0) {
			lines.push('tags:');
			for (const tag of s.tags) lines.push(`  - ${tag}`);
		}
		return lines.join('\n');
	}

	function closeModal() {
		viewingSuggestion = null;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && viewingSuggestion) closeModal();
	}

	onMount(async () => {
		const resp = await fetchCustomers();
		customers = resp.customers;
	});

	const selectedCustomerName = $derived(
		customers.find((c) => c.id === $selectedCustomerId)?.name ?? null
	);

	async function runSigmaGeneration() {
		if (selectedCustomerName === null || running) return;
		error = null;
		running = true;
		processedRules = 0;
		totalRules = 0;
		failedRules = 0;
		status = 'starting';

		try {
			const created = await startSigmaGeneration(selectedCustomerName);
			totalRules = created.total_rules;
			status = created.status;

			if (created.total_rules === 0) {
				status = 'completed';
				running = false;
				return;
			}

			streamProgress(created.id);
		} catch (e) {
			error = 'Failed to start Sigma generation';
			running = false;
		}
	}

	function streamProgress(jobId: number) {
		eventSource = new EventSource(`${API_BASE}/recommendations/sigma-jobs/${jobId}/stream`);

		eventSource.onmessage = (event) => {
			const data = JSON.parse(event.data);
			processedRules = data.processed_rules;
			totalRules = data.total_rules;
			failedRules = data.failed_rules;
			status = data.status;

			if (data.status !== 'running') {
				eventSource?.close();
				running = false;
			}
		};

		eventSource.onerror = () => {
			error = 'Lost connection to the progress stream';
			eventSource?.close();
			running = false;
		};
	}

	const progressPercent = $derived(totalRules > 0 ? Math.round((processedRules / totalRules) * 100) : 0);

	type Tab = 'mitre' | 'logsource';
	let activeTab = $state<Tab>('mitre');

	let mitreGaps = $state<MitreGap[]>([]);
	let logSourceGaps = $state<LogSourceGap[]>([]);
	let feedLoading = $state(true);
	let feedError = $state<string | null>(null);

	const NO_PEER_DISPLAY_CAP = 6;

	$effect(() => {
		const customerName = selectedCustomerName;
		if (customerName === null) return;

		feedLoading = true;
		feedError = null;
		Promise.all([fetchMitreGaps(customerName), fetchLogSourceGaps(customerName)])
			.then(([mitre, logsource]) => {
				mitreGaps = mitre;
				logSourceGaps = logsource;
			})
			.catch((e) => {
				feedError = e instanceof ApiError ? e.message : 'Failed to load recommendations';
			})
			.finally(() => {
				feedLoading = false;
			});
	});

	type Feasibility = 'ready' | 'needs-log-source' | 'no-peer';
	const FEASIBILITY_RANK: Record<Feasibility, number> = { ready: 0, 'needs-log-source': 1, 'no-peer': 2 };

	function gapFeasibility(gap: { suggested_rules: PeerRuleSuggestion[] }): Feasibility {
		if (gap.suggested_rules.length === 0) return 'no-peer';
		const anyReady = gap.suggested_rules.some((s) => s.customer_has_required_log_source);
		return anyReady ? 'ready' : 'needs-log-source';
	}

	function bestSuggestion(gap: { suggested_rules: PeerRuleSuggestion[] }): PeerRuleSuggestion | null {
		if (gap.suggested_rules.length === 0) return null;
		return gap.suggested_rules.find((s) => s.customer_has_required_log_source) ?? gap.suggested_rules[0];
	}

	interface TacticGroup {
		tactic: string;
		gaps: MitreGap[];
	}

	const mitreGroups = $derived.by((): TacticGroup[] => {
		const groups = new Map<string, MitreGap[]>();
		for (const gap of mitreGaps) {
			const key = gap.tactic_names[0] ?? 'Other';
			if (!groups.has(key)) groups.set(key, []);
			groups.get(key)!.push(gap);
		}
		const result: TacticGroup[] = [];
		for (const [tactic, gaps] of groups) {
			gaps.sort((a, b) => FEASIBILITY_RANK[gapFeasibility(a)] - FEASIBILITY_RANK[gapFeasibility(b)]);
			result.push({ tactic, gaps });
		}
		result.sort((a, b) => a.tactic.localeCompare(b.tactic));
		return result;
	});

	const logSourceSorted = $derived(
		[...logSourceGaps].sort(
			(a, b) => FEASIBILITY_RANK[gapFeasibility(a)] - FEASIBILITY_RANK[gapFeasibility(b)]
		)
	);

	function visibleGaps<T extends { suggested_rules: PeerRuleSuggestion[] }>(gaps: T[]): T[] {
		const withPeer = gaps.filter((g) => g.suggested_rules.length > 0);
		const noPeer = gaps.filter((g) => g.suggested_rules.length === 0).slice(0, NO_PEER_DISPLAY_CAP);
		return [...withPeer, ...noPeer];
	}

	function hiddenCount<T extends { suggested_rules: PeerRuleSuggestion[] }>(gaps: T[]): number {
		const noPeerTotal = gaps.filter((g) => g.suggested_rules.length === 0).length;
		return Math.max(0, noPeerTotal - NO_PEER_DISPLAY_CAP);
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="header">
	<h1>Recommendations</h1>
	<p class="subtitle">Rule suggestions based on coverage gaps compared to peer customers.</p>
</div>

<div class="panel">
	<div class="run-row">
		<span class="customer-label">
			{selectedCustomerName ? `Customer: ${selectedCustomerName}` : 'Loading customer…'}
		</span>
		<button onclick={runSigmaGeneration} disabled={running || selectedCustomerName === null}>
			{running ? 'Running…' : 'Run Sigma Generation'}
		</button>
	</div>

	{#if error}
		<div class="empty-state error">{error}</div>
	{/if}

	{#if status}
		<div class="progress-section">
			<div class="progress-bar-track">
				<div class="progress-bar-fill" style="width: {progressPercent}%"></div>
			</div>
			<div class="progress-stats">
				<span>{processedRules} / {totalRules} rules processed</span>
				{#if failedRules > 0}
					<span class="failed-count">{failedRules} failed</span>
				{/if}
				<span class="status-badge status-{status}">{status}</span>
			</div>
		</div>
	{/if}
</div>

<div class="tabs">
	<button class="tab" class:active={activeTab === 'mitre'} onclick={() => (activeTab = 'mitre')}>
		Mitre coverage gaps
	</button>
	<button class="tab" class:active={activeTab === 'logsource'} onclick={() => (activeTab = 'logsource')}>
		Log source gaps
	</button>
</div>

{#if feedLoading}
	<p class="muted">Loading recommendations…</p>
{:else if feedError}
	<div class="empty-state error">{feedError}</div>
{:else if activeTab === 'mitre'}
	{#if mitreGroups.length === 0}
		<p class="muted">No coverage gaps found.</p>
	{:else}
		{#each mitreGroups as group (group.tactic)}
			<div class="tactic-row">
				<div class="tactic-header">
					<h3>{group.tactic}</h3>
					<span class="gap-count">{group.gaps.length} gaps</span>
				</div>
				<div class="card-scroll">
					{#each visibleGaps(group.gaps) as gap (gap.technique_id)}
						{@const feasibility = gapFeasibility(gap)}
						{@const suggestion = bestSuggestion(gap)}
						<div class="rec-card">
							<div class="rec-card-top">
								{#if feasibility === 'ready'}
									<span class="badge badge-ready">Ready</span>
								{:else if feasibility === 'needs-log-source'}
									<span class="badge badge-warning">Needs log source</span>
								{:else}
									<span class="badge badge-muted">No peer yet</span>
								{/if}
								{#if suggestion?.mitre_source}
									<span class="source-tag">{suggestion.mitre_source}</span>
								{/if}
							</div>
							<p class="rec-title">{gap.technique_name ?? gap.technique_id}</p>
							<p class="rec-meta">
								{gap.technique_id}{#if suggestion} · from {suggestion.source_customer_name}{/if}
							</p>
							{#if suggestion}
								<button class="view-btn" onclick={() => (viewingSuggestion = suggestion)}>View rule</button>
							{:else}
								<span class="view-btn disabled">Nothing to view</span>
							{/if}
						</div>
					{/each}
					{#if hiddenCount(group.gaps) > 0}
						<div class="more-card">
							<span>+{hiddenCount(group.gaps)} more with no peer coverage yet</span>
						</div>
					{/if}
				</div>
			</div>
		{/each}
	{/if}
{:else if logSourceSorted.length === 0}
	<p class="muted">No log source gaps found.</p>
{:else}
	<div class="card-scroll wrap">
		{#each visibleGaps(logSourceSorted) as gap (gap.qradar_type_id)}
			{@const feasibility = gapFeasibility(gap)}
			{@const suggestion = bestSuggestion(gap)}
			<div class="rec-card">
				<div class="rec-card-top">
					{#if feasibility === 'ready'}
						<span class="badge badge-ready">Ready</span>
					{:else if feasibility === 'needs-log-source'}
						<span class="badge badge-warning">Needs log source</span>
					{:else}
						<span class="badge badge-muted">No peer yet</span>
					{/if}
				</div>
				<p class="rec-title">{gap.log_source_type_name}</p>
				<p class="rec-meta">
					{#if suggestion}{suggestion.title} · from {suggestion.source_customer_name}{/if}
				</p>
				{#if suggestion}
					<button class="view-btn" onclick={() => (viewingSuggestion = suggestion)}>View rule</button>
				{:else}
					<span class="view-btn disabled">Nothing to view</span>
				{/if}
			</div>
		{/each}
		{#if hiddenCount(logSourceSorted) > 0}
			<div class="more-card">
				<span>+{hiddenCount(logSourceSorted)} more with no peer coverage yet</span>
			</div>
		{/if}
	</div>
{/if}


{#if viewingSuggestion}
	<div class="modal-backdrop" role="presentation" onclick={closeModal}>
		<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
			<div class="modal-header">
				<div>
					<h2 id="modal-title">{viewingSuggestion.title}</h2>
					<p class="modal-subtitle">
						From {viewingSuggestion.source_customer_name}
						{#if viewingSuggestion.mitre_source}
							· {viewingSuggestion.mitre_source}
							{#if viewingSuggestion.mitre_confidence}
								({viewingSuggestion.mitre_confidence} confidence){/if}
						{/if}
					</p>
				</div>
				<button class="close-btn" onclick={closeModal} aria-label="Close">✕</button>
			</div>

			{#if !viewingSuggestion.customer_has_required_log_source}
				<div class="modal-warning">
					Requires a log source you haven't onboarded yet: {viewingSuggestion.required_log_source_types.join(', ')}
				</div>
			{/if}

			<pre class="yaml-block">{formatAsSigmaYaml(viewingSuggestion)}</pre>
		</div>
	</div>
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

	.panel {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1.25rem;
		margin-bottom: 2rem;
	}

	.run-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.customer-label {
		font-size: 0.9rem;
		font-weight: 600;
	}

	button {
		padding: 0.6rem 1.1rem;
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		color: var(--accent);
		font-size: 0.9rem;
		font-weight: 500;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.progress-section {
		margin-top: 1.25rem;
	}
	.progress-bar-track {
		width: 100%;
		height: 10px;
		background: var(--bg);
		border-radius: 999px;
		overflow: hidden;
		border: 1px solid var(--border);
	}
	.progress-bar-fill {
		height: 100%;
		background: var(--accent);
		transition: width 0.3s ease;
	}
	.progress-stats {
		display: flex;
		align-items: center;
		gap: 1rem;
		margin-top: 0.6rem;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.failed-count {
		color: var(--warning);
	}
	.status-badge {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0.2rem 0.55rem;
		border-radius: 999px;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		margin-left: auto;
	}
	.status-running {
		background: var(--warning-dim);
		color: var(--warning);
	}
	.status-completed {
		background: var(--accent-dim);
		color: var(--accent);
	}
	.status-failed {
		background: var(--warning-dim);
		color: var(--warning);
	}

	.tabs {
		display: flex;
		gap: 0.5rem;
		border-bottom: 1px solid var(--border);
		margin-bottom: 1.5rem;
	}
	.tab {
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		border-radius: 0;
		padding: 0.6rem 0.25rem;
		margin-right: 1.25rem;
		font-size: 0.9rem;
		font-weight: 500;
		color: var(--text-muted);
	}
	.tab.active {
		border-bottom-color: var(--accent);
		color: var(--text);
	}

	.tactic-row {
		margin-bottom: 1.75rem;
	}
	.tactic-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 0.6rem;
	}
	.tactic-header h3 {
		font-size: 0.95rem;
		margin: 0;
	}
	.gap-count {
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.card-scroll {
		display: flex;
		gap: 0.75rem;
		overflow-x: auto;
		padding-bottom: 0.5rem;
	}
	.card-scroll.wrap {
		flex-wrap: wrap;
	}

	.rec-card {
		min-width: 220px;
		max-width: 220px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1rem;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
	}
	.rec-card-top {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 0.5rem;
	}
	.badge {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0.15rem 0.5rem;
		border-radius: var(--radius);
	}
	.badge-ready {
		background: var(--accent-dim);
		color: var(--accent);
	}
	.badge-warning {
		background: var(--warning-dim);
		color: var(--warning);
	}
	.badge-muted {
		background: var(--surface-hover);
		color: var(--text-muted);
	}
	.source-tag {
		font-size: 0.7rem;
		color: var(--text-faint);
	}
	.rec-title {
		font-size: 0.85rem;
		font-weight: 500;
		margin: 0 0 0.25rem;
		line-height: 1.4;
	}
	.rec-meta {
		font-size: 0.75rem;
		color: var(--text-muted);
		margin: 0 0 0.6rem;
		flex: 1;
	}
	.view-btn {
		display: block;
		width: 100%;
		box-sizing: border-box;
		text-align: center;
		font-size: 0.75rem;
		padding: 0.4rem 0.6rem;
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		color: var(--accent);
		text-decoration: none;
	}
	.view-btn.disabled {
		background: none;
		border-color: var(--border);
		color: var(--text-faint);
	}

	.more-card {
		min-width: 160px;
		display: flex;
		align-items: center;
		justify-content: center;
		text-align: center;
		font-size: 0.75rem;
		color: var(--text-muted);
		border: 1px dashed var(--border);
		border-radius: var(--radius);
		padding: 1rem;
		flex-shrink: 0;
	}

	.muted {
		color: var(--text-muted);
		font-size: 0.9rem;
	}
	.empty-state {
		padding: 1rem;
		text-align: center;
		color: var(--text-muted);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
	}
	.empty-state.error {
		color: var(--warning);
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: 1.5rem;
	}
	.modal {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		max-width: 640px;
		width: 100%;
		max-height: 80vh;
		overflow-y: auto;
		padding: 1.5rem;
	}
	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 1rem;
	}
	.modal-header h2 {
		font-size: 1.1rem;
		margin: 0 0 0.25rem;
	}
	.modal-subtitle {
		font-size: 0.8rem;
		color: var(--text-muted);
		margin: 0;
	}
	.close-btn {
		background: none;
		border: none;
		padding: 0.25rem 0.5rem;
		font-size: 1rem;
		color: var(--text-muted);
	}
	.modal-warning {
		background: var(--warning-dim);
		color: var(--warning);
		border-radius: var(--radius);
		padding: 0.6rem 0.8rem;
		font-size: 0.8rem;
		margin-bottom: 1rem;
	}
	.yaml-block {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1rem;
		font-family: 'IBM Plex Mono', ui-monospace, monospace;
		font-size: 0.8rem;
		line-height: 1.6;
		overflow-x: auto;
		white-space: pre;
		margin: 0;
	}
</style>