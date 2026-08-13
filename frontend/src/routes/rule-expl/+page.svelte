<script lang="ts">
	import { askAgent } from '$lib/api/agent';
	import { ApiError } from '$lib/api/client';
	import type { ChatTurn } from '$lib/types/agent';
	import { Send, HelpCircle, ShieldAlert, Ban, AlertTriangle } from 'lucide-svelte';

	// TODO: replace with a real customer selector once there's more than one
	const CUSTOMER_ID = 1;

	let turns = $state<ChatTurn[]>([]);
	let input = $state('');
	let loading = $state(false);

	function rowColumns(rows: Record<string, unknown>[]): string[] {
		return rows.length > 0 ? Object.keys(rows[0]) : [];
	}

	function formatCell(value: unknown): string {
		if (value === null || value === undefined) return '—';
		if (typeof value === 'object') return JSON.stringify(value);
		return String(value);
	}

	async function submit() {
		const question = input.trim();
		if (!question || loading) return;

		turns.push({ role: 'user', text: question });
		input = '';
		loading = true;

		try {
			const response = await askAgent(question, CUSTOMER_ID);
			turns.push({ role: 'assistant', text: '', response });
		} catch (e) {
			const message = e instanceof ApiError ? e.message : 'Request failed — is the backend running?';
			turns.push({
				role: 'assistant',
				text: '',
				response: { status: 'llm_error', query: null, rows: null, retried: null, question: null, reason: null, error: message }
			});
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit();
		}
	}
</script>

<div class="header">
	<h1>Rule Analyzer</h1>
	<p class="subtitle">Ask a question about your ruleset in plain English.</p>
</div>

<div class="chat">
	{#if turns.length === 0}
		<div class="empty-state">
			Try: "Which rules check the Command field?" or "Which rules depend on SYSTEM-1300?"
		</div>
	{/if}

	{#each turns as turn, i (i)}
		{#if turn.role === 'user'}
			<div class="turn user">
				<div class="bubble">{turn.text}</div>
			</div>
		{:else if turn.response}
			<div class="turn assistant">
				{#if turn.response.status === 'ok'}
					<div class="bubble result">
						{#if turn.response.retried}
							<div class="meta">Corrected after an initial attempt.</div>
						{/if}
						{#if turn.response.query}
							<pre class="cypher">{turn.response.query}</pre>
						{/if}
						{#if turn.response.rows && turn.response.rows.length > 0}
							<div class="table-wrap">
								<table>
									<thead>
										<tr>
											{#each rowColumns(turn.response.rows) as col (col)}
												<th>{col}</th>
											{/each}
										</tr>
									</thead>
									<tbody>
										{#each turn.response.rows as row, ri (ri)}
											<tr>
												{#each rowColumns(turn.response.rows) as col (col)}
													<td>{formatCell(row[col])}</td>
												{/each}
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
							<div class="meta">{turn.response.rows.length} result{turn.response.rows.length === 1 ? '' : 's'}</div>
						{:else}
							<div class="meta">No matching results.</div>
						{/if}
					</div>
				{:else if turn.response.status === 'needs_clarification'}
					<div class="bubble clarify">
						<HelpCircle size={16} strokeWidth={2} />
						<span>{turn.response.question}</span>
					</div>
				{:else if turn.response.status === 'not_answerable'}
					<div class="bubble not-answerable">
						<Ban size={16} strokeWidth={2} />
						<span>{turn.response.reason}</span>
					</div>
				{:else if turn.response.status === 'rejected'}
					<div class="bubble rejected">
						<ShieldAlert size={16} strokeWidth={2} />
						<span>Query blocked by the safety layer: {turn.response.error}</span>
					</div>
				{:else}
					<div class="bubble error">
						<AlertTriangle size={16} strokeWidth={2} />
						<span>{turn.response.error}</span>
					</div>
				{/if}
			</div>
		{/if}
	{/each}

	{#if loading}
		<div class="turn assistant">
			<div class="bubble thinking">Thinking…</div>
		</div>
	{/if}
</div>

<div class="input-bar">
	<textarea
		bind:value={input}
		onkeydown={handleKeydown}
		placeholder="Ask about your rules…"
		rows="1"
	></textarea>
	<button onclick={submit} disabled={loading || !input.trim()}>
		<Send size={16} strokeWidth={2} />
	</button>
</div>

<style>
	.header {
		margin-bottom: 1.25rem;
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

	.chat {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		min-height: 200px;
		margin-bottom: 1rem;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
		color: var(--text-muted);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		font-size: 0.875rem;
	}

	.turn {
		display: flex;
	}
	.turn.user {
		justify-content: flex-end;
	}
	.turn.assistant {
		justify-content: flex-start;
	}

	.bubble {
		max-width: 85%;
		padding: 0.65rem 0.9rem;
		border-radius: var(--radius);
		font-size: 0.9rem;
		line-height: 1.5;
	}
	.turn.user .bubble {
		background: var(--accent-dim);
		color: var(--text);
	}
	.bubble.thinking {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-muted);
	}
	.bubble.result {
		background: var(--surface);
		border: 1px solid var(--border);
		max-width: 100%;
		width: 100%;
	}
	.bubble.clarify {
		background: var(--warning-dim);
		border: 1px solid var(--warning);
		color: var(--warning);
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
	}
	.bubble.not-answerable {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-muted);
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
	}
	.bubble.rejected {
		background: var(--warning-dim);
		border: 1px solid var(--warning);
		color: var(--warning);
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
	}
	.bubble.error {
		background: var(--warning-dim);
		border: 1px solid var(--warning);
		color: var(--warning);
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
	}

	.cypher {
		font-family: 'IBM Plex Mono', ui-monospace, monospace;
		font-size: 0.75rem;
		background: var(--bg);
		border-radius: 6px;
		padding: 0.65rem 0.8rem;
		overflow-x: auto;
		white-space: pre-wrap;
		color: var(--text-muted);
		margin: 0 0 0.75rem;
	}

	.table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		text-align: left;
		padding: 0.5rem 0.75rem;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		color: var(--text-faint);
		background: var(--bg);
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	td {
		padding: 0.45rem 0.75rem;
		font-size: 0.8rem;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	tr:last-child td {
		border-bottom: none;
	}

	.meta {
		color: var(--text-faint);
		font-size: 0.75rem;
		margin-top: 0.5rem;
	}

	.input-bar {
		display: flex;
		gap: 0.5rem;
		position: sticky;
		bottom: 1rem;
	}
	textarea {
		flex: 1;
		resize: none;
		padding: 0.7rem 0.9rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		font-size: 0.9rem;
		font-family: inherit;
	}
	textarea:focus {
		outline: none;
		border-color: var(--accent);
	}
	.input-bar button {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 42px;
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		color: var(--accent);
		cursor: pointer;
	}
	.input-bar button:disabled {
		opacity: 0.4;
		cursor: default;
	}
</style>