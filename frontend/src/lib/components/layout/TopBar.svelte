<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchCustomers, type Customer } from '$lib/api/customers';
	import { selectedCustomerId } from '$lib/stores/customer';
	import { ApiError } from '$lib/api/client';

	let customers = $state<Customer[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			const resp = await fetchCustomers();
			customers = resp.customers;
			if ($selectedCustomerId === null && customers.length > 0) {
				selectedCustomerId.set(customers[0].id);
			}
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to load customers';
		} finally {
			loading = false;
		}
	});

	function handleChange(event: Event) {
		const id = Number((event.target as HTMLSelectElement).value);
		selectedCustomerId.set(id);
	}
</script>

<header class="topbar">
	<div class="context">
		<span class="context-label">Customer</span>
		{#if loading}
			<span class="context-value muted">Loading…</span>
		{:else if error}
			<span class="context-value error-text">{error}</span>
		{:else}
			<select class="context-select" value={$selectedCustomerId} onchange={handleChange}>
				{#each customers as customer (customer.id)}
					<option value={customer.id}>{customer.name}</option>
				{/each}
			</select>
		{/if}
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

	.context-value.muted {
		color: var(--text-muted);
		font-weight: 400;
	}

	.context-value.error-text {
		color: var(--warning);
		font-weight: 400;
	}

	.context-select {
		font-size: 0.9rem;
		font-weight: 600;
		color: var(--text);
		background: transparent;
		border: none;
		border-bottom: 1px dashed var(--border);
		padding: 0 0.2rem 0.1rem;
		cursor: pointer;
	}

	.context-select:hover,
	.context-select:focus {
		border-bottom-color: var(--accent);
		outline: none;
	}

	.context-select option {
		background: var(--bg);
		color: var(--text);
		font-weight: 400;
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