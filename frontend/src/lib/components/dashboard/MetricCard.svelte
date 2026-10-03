<script lang="ts">
	let {
		label,
		value,
		tone = 'neutral',
		hint
	}: {
		label: string;
		value: number;
		tone?: 'accent' | 'warning' | 'neutral';
		hint?: string;
	} = $props();
</script>

<div class="card" data-tone={tone}>
	<div class="edge"></div>
	<div class="content">
		<span class="label">{label}</span>
		<span class="value mono">{value.toLocaleString()}</span>
		{#if hint}
			<span class="hint">{hint}</span>
		{/if}
	</div>
</div>

<style>
	.card {
		display: flex;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		overflow: hidden;
	}

	.edge {
		width: 3px;
		flex-shrink: 0;
		background: var(--text-faint);
	}

	.card[data-tone='accent'] .edge {
		background: var(--accent);
	}

	.card[data-tone='warning'] .edge {
		background: var(--warning);
	}

	.content {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 1.1rem 1.3rem;
		flex: 1;
	}

	.label {
		font-size: 0.78rem;
		color: var(--text-muted);
		font-weight: 500;
	}

	.value {
		font-size: 1.9rem;
		font-weight: 600;
		letter-spacing: -0.01em;
	}

	.hint {
		font-size: 0.75rem;
		color: var(--text-faint);
	}
</style>