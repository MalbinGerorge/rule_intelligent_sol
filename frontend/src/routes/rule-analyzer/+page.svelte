<script lang="ts">
	import { fetchAllRules } from '$lib/api/rules';
	import { startInvestigation, getInvestigation, listInvestigations } from '$lib/api/rule_analyzer';
	import { ApiError } from '$lib/api/client';
	import type { Rule } from '$lib/types/rule';
	import type { InvestigationDetail, InvestigationListItem } from '$lib/api/rule_analyzer';
	import { selectedCustomerId } from '$lib/stores/customer';

	// -- Rule picker state --
	let searchText = $state('');
	let allRules = $state<Rule[]>([]);
	let rulesLoading = $state(true);
	let rulesError = $state<string | null>(null);
	let selectedRuleId = $state<number | null>(null);
	let selectedRuleName = $state<string>('');

	const filteredRules = $derived(
		searchText.trim() === ''
			? []
			: allRules
					.filter((r) => (r.name ?? '').toLowerCase().includes(searchText.trim().toLowerCase()))
					.slice(0, 20)
	);

	// -- Investigation state --
	let current = $state<InvestigationDetail | null>(null);
	let polling = $state(false);
	let investigationError = $state<string | null>(null);
	let history = $state<InvestigationListItem[]>([]);
	let historyTotal = $state(0);
	let historyOffset = $state(0);
	const HISTORY_PAGE_SIZE = 20;
	let showTrace = $state(false);
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	// Runs on initial mount AND every time the selected customer changes
	// (replaces the old onMount -- $effect covers both cases in one
	// place). Resets ALL rule-scoped state first -- a selected rule or
	// in-progress investigation belongs to the PREVIOUS customer and
	// must not linger on screen after switching -- then loads the new
	// customer's rule list.
	$effect(() => {
		const customerId = $selectedCustomerId;
		if (customerId === null) return;

		selectedRuleId = null;
		selectedRuleName = '';
		searchText = '';
		current = null;
		history = [];
		historyTotal = 0;
		investigationError = null;
		if (pollTimer) clearInterval(pollTimer);
		polling = false;

		rulesLoading = true;
		rulesError = null;
		fetchAllRules(customerId)
			.then((rules) => {
				allRules = rules;
			})
			.catch((e) => {
				rulesError = e instanceof ApiError ? e.message : 'Failed to load rules';
			})
			.finally(() => {
				rulesLoading = false;
			});
	});

	function selectRule(rule: Rule) {
		selectedRuleId = rule.id;
		selectedRuleName = rule.name ?? `Rule #${rule.id}`;
		searchText = '';
		current = null;
		loadHistory();
	}

	async function loadHistory() {
		if (selectedRuleId === null) return;
		try {
			const resp = await listInvestigations(selectedRuleId, HISTORY_PAGE_SIZE, historyOffset);
			history = resp.items;
			historyTotal = resp.total;
		} catch (e) {
			// history is secondary -- a failure here shouldn't block the main flow
			history = [];
		}
	}

	async function runInvestigation() {
		if (selectedRuleId === null || $selectedCustomerId === null) return;
		investigationError = null;
		showTrace = false;
		try {
			const created = await startInvestigation(selectedRuleId);
			current = {
				...created,
				rule_id: selectedRuleId,
				customer_id: $selectedCustomerId,
				error: null,
				chain_analysis: null,
				final_report: null,
				rendered_report: null,
				trace: null,
				tool_calls_made: null,
				created_at: new Date().toISOString()
			} as InvestigationDetail;
			poll(created.id);
		} catch (e) {
			investigationError = e instanceof ApiError ? e.message : 'Failed to start investigation';
		}
	}

	function poll(investigationId: number) {
		polling = true;
		pollTimer = setInterval(async () => {
			try {
				const detail = await getInvestigation(investigationId);
				current = detail;
				if (detail.status !== 'running') {
					polling = false;
					if (pollTimer) clearInterval(pollTimer);
					loadHistory();
				}
			} catch (e) {
				polling = false;
				if (pollTimer) clearInterval(pollTimer);
				investigationError = e instanceof ApiError ? e.message : 'Lost connection while polling';
			}
		}, 2000);
	}

	function viewPastInvestigation(id: number) {
		if (pollTimer) clearInterval(pollTimer);
		polling = false;
		showTrace = false;
		getInvestigation(id).then((detail) => (current = detail));
	}

	function confidenceClass(confidence: string): string {
		if (confidence === 'high') return 'confidence-high';
		if (confidence === 'medium') return 'confidence-medium';
		return 'confidence-low';
	}
</script>

<div class="header">
	<h1>Rule Analyzer</h1>
	<p class="subtitle">Investigate why a rule may not be firing as expected.</p>
</div>

<div class="panel picker-panel">
	{#if rulesLoading}
		<p class="muted">Loading rules…</p>
	{:else if rulesError}
		<div class="empty-state error">{rulesError}</div>
	{:else}
		<input type="text" bind:value={searchText} placeholder="Search for a rule by name…" />
		{#if filteredRules.length > 0}
			<ul class="search-results">
				{#each filteredRules as rule (rule.id)}
					<li>
						<button onclick={() => selectRule(rule)}>{rule.name ?? `Rule #${rule.id}`}</button>
					</li>
				{/each}
			</ul>
		{/if}

		<div class="selected-rule-row">
			<span class="selected-rule-name">
				{selectedRuleId !== null ? `Selected: ${selectedRuleName}` : 'No rule selected'}
			</span>
			<button class="run-button" onclick={runInvestigation} disabled={polling || selectedRuleId === null}>
				{polling ? 'Investigating…' : 'Run Investigation'}
			</button>
		</div>
	{/if}
</div>

{#if investigationError}
	<div class="empty-state error">{investigationError}</div>
{/if}

{#if current}
	<div class="panel result-panel">
		{#if current.status === 'running'}
			<div class="status-running">
				<span class="spinner"></span>
				Investigating — this can take up to a couple of minutes (live QRadar checks, AQL searches).
			</div>
		{:else if current.status === 'failed'}
			<div class="empty-state error">Investigation failed: {current.error}</div>
		{:else if current.status === 'completed' && current.final_report}
			<div class="report">
				<section>
					<h2>What This Rule Detects</h2>
					<p>{current.final_report.detection_intent}</p>
				</section>

				<section>
					<h2>Structural Assessment</h2>
					<p>{current.final_report.structural_summary}</p>
				</section>

				<section>
					<h2>Most Likely Root Causes</h2>
					{#each current.final_report.root_causes as cause, i (i)}
						<div class="root-cause">
							<div class="root-cause-header">
								<span class="rank">{i + 1}.</span>
								<span class="cause-text">{cause.cause}</span>
								<span class="confidence-badge {confidenceClass(cause.confidence)}"
									>{cause.confidence}</span
								>
							</div>
							<div class="evidence">
								<strong>Evidence:</strong>
								<ul>
									{#each cause.evidence as e}
										<li>{e}</li>
									{/each}
								</ul>
							</div>
							<div class="next-steps">
								<strong>Next steps:</strong>
								<ul>
									{#each cause.next_steps as step}
										<li>{step}</li>
									{/each}
								</ul>
							</div>
						</div>
					{/each}
				</section>

				<section>
					<h2>Overall Recommendation</h2>
					<p>{current.final_report.overall_recommendation}</p>
				</section>

				{#if current.final_report.additional_findings.length > 0}
					<section class="additional-findings">
						<h2>Additional Findings / Potential New Rule Opportunities</h2>
						{#each current.final_report.additional_findings as finding, i (i)}
							<div class="finding">
								<div class="finding-header">{i + 1}. {finding.observation}</div>
								<ul>
									{#each finding.evidence as e}
										<li>{e}</li>
									{/each}
								</ul>
								<p><strong>Suggested next step:</strong> {finding.suggested_next_step}</p>
							</div>
						{/each}
					</section>
				{/if}

				<section class="meta-row">
					<span class="muted">{current.tool_calls_made} tool call(s)</span>
					<button class="trace-toggle" onclick={() => (showTrace = !showTrace)}>
						{showTrace ? 'Hide' : 'Show'} reasoning trace
					</button>
				</section>

				{#if showTrace && current.trace}
					<pre class="trace-view mono">{current.trace}</pre>
				{/if}
			</div>
		{/if}
	</div>
{/if}

{#if selectedRuleId !== null}
	<div class="panel history-panel">
		<h2>Past Investigations ({historyTotal})</h2>
		{#if history.length === 0}
			<p class="muted">No past investigations for this rule yet.</p>
		{:else}
			<ul class="history-list">
				{#each history as item (item.id)}
					<li>
						<button class="history-item" onclick={() => viewPastInvestigation(item.id)}>
							<span class="status-dot status-{item.status}"></span>
							{new Date(item.created_at).toLocaleString()}
							<span class="tool-count muted">{item.tool_calls_made ?? 0} calls</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
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
		padding: 1rem 1.1rem;
		margin-bottom: 1.5rem;
	}
	.panel h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-faint);
		margin: 0 0 0.75rem;
	}

	.picker-panel input {
		width: 100%;
		padding: 0.65rem 0.9rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		font-size: 0.9rem;
	}
	.picker-panel input:focus {
		outline: none;
		border-color: var(--accent);
	}
	.search-results {
		list-style: none;
		margin: 0.5rem 0 0;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		max-height: 240px;
		overflow-y: auto;
	}
	.search-results button {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		color: var(--text);
		padding: 0.5rem 0.65rem;
		cursor: pointer;
		font-size: 0.875rem;
	}
	.search-results button:hover {
		background: var(--surface-hover);
	}
	.selected-rule-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 1rem;
	}
	.selected-rule-name {
		font-weight: 600;
		font-size: 0.9rem;
	}
	.run-button {
		padding: 0.6rem 1.1rem;
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		color: var(--accent);
		font-size: 0.9rem;
		font-weight: 500;
		cursor: pointer;
	}
	.run-button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.status-running {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 0.9rem;
	}
	.spinner {
		width: 15px;
		height: 15px;
		border: 2px solid var(--accent);
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
		flex-shrink: 0;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.root-cause {
		border-top: 1px solid var(--border);
		padding: 0.75rem 0;
	}
	.root-cause:first-of-type {
		border-top: none;
	}
	.root-cause-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-weight: 600;
		font-size: 0.9rem;
	}
	.confidence-badge {
		font-size: 0.65rem;
		padding: 0.15rem 0.5rem;
		border-radius: 999px;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.confidence-high {
		background: var(--accent-dim);
		color: var(--accent);
	}
	.confidence-medium {
		background: var(--warning-dim);
		color: var(--warning);
	}
	.confidence-low {
		background: var(--surface-hover);
		color: var(--text-muted);
	}

	.evidence,
	.next-steps {
		font-size: 0.85rem;
		margin-top: 0.4rem;
	}
	.evidence ul,
	.next-steps ul {
		margin: 0.25rem 0 0;
		padding-left: 1.2rem;
	}

	.meta-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 1rem;
		font-size: 0.8rem;
	}
	.trace-toggle {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
		padding: 0.3rem 0.7rem;
		border-radius: var(--radius);
		cursor: pointer;
		font-size: 0.8rem;
	}
	.trace-view {
		font-size: 0.75rem;
		background: var(--bg);
		padding: 0.9rem;
		border-radius: var(--radius);
		overflow-x: auto;
		max-height: 400px;
		margin-top: 0.75rem;
	}

	.history-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.history-item {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		color: var(--text);
		padding: 0.5rem;
		cursor: pointer;
		font-size: 0.85rem;
		border-radius: var(--radius);
	}
	.history-item:hover {
		background: var(--surface-hover);
	}
	.status-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.status-dot.status-completed {
		background: var(--accent);
	}
	.status-dot.status-failed {
		background: var(--warning);
	}
	.status-dot.status-running {
		background: var(--warning);
	}
	.tool-count {
		margin-left: auto;
		font-size: 0.75rem;
	}

	.mono {
		font-family: 'IBM Plex Mono', ui-monospace, monospace;
	}
	.muted {
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	.empty-state {
		padding: 1.25rem;
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