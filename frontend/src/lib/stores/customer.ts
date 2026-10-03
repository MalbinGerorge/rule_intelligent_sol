/**
 * Shared, app-wide selected customer -- the ONE source of truth
 * every UI (rule health, graph search, rule analyzer, recommendations)
 * reads from, instead of each page hardcoding its own CUSTOMER_ID.
 *
 * Persisted to localStorage so the selection survives a page refresh,
 * not just navigation between pages.
 */
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const STORAGE_KEY = 'rule_intelligent_sol_selected_customer_id';

function createSelectedCustomerStore() {
	const initial = browser ? Number(localStorage.getItem(STORAGE_KEY)) || null : null;
	const { subscribe, set } = writable<number | null>(initial);

	return {
		subscribe,
		set: (id: number) => {
			if (browser) localStorage.setItem(STORAGE_KEY, String(id));
			set(id);
		}
	};
}

export const selectedCustomerId = createSelectedCustomerStore();