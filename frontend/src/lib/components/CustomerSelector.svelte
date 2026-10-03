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

<div class="customer-selector">
	{#if loading}
		<span class="muted">Loading customers…</span>
	{:else if error}
		<span class="error">{error}</span>
	{:else}
		<label for="customer-select" class="label">Customer</label>
		<select id="customer-select" value={$selectedCustomerId} onchange={handleChange}>
			{#each customers as customer (customer.id)}
				<option value={customer.id}>{customer.name}</option>
			{/each}
		</select>
	{/if}
</div>

<style>
	.customer-selector {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border);
	}
	.label {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-faint);
	}
	select {
		padding: 0.4rem 0.6rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		font-size: 0.85rem;
	}
	.muted {
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	.error {
		color: var(--warning);
		font-size: 0.85rem;
	}
</style>