<script lang="ts">
	let { customerName = 'Cotecna' }: { customerName?: string } = $props();
</script>

<header class="topbar">
	<div class="context">
		<span class="context-label">Customer</span>
		<span class="context-value">{customerName}</span>
	</div>

	<div class="user">
		<div class="user-info">
			<span class="user-name">Analyst</span>
			<span class="user-role">Detection Engineering</span>
		</div>
		<div class="avatar">A</div>
	</div>
</header>

<style>
	.topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.9rem 1.5rem;
		border-bottom: 1px solid var(--border);
		background: var(--bg);
	}

	.context {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}

	.context-label {
		font-size: 0.75rem;
		color: var(--text-faint);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.context-value {
		font-size: 0.9rem;
		font-weight: 600;
	}

	.user {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.user-info {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
	}

	.user-name {
		font-size: 0.85rem;
		font-weight: 600;
	}

	.user-role {
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background: var(--accent-dim);
		color: var(--accent);
		display: flex;
		align-items: center;
		justify-content: center;
		font-weight: 600;
		font-size: 0.8rem;
	}
</style>