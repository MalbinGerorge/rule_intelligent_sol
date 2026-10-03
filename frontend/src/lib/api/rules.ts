import { apiGet } from './client';
import type { Rule, RulesResponse, RuleHealthMetrics } from '$lib/types/rule';

export function fetchRules(customerId: number, objectType?: string): Promise<RulesResponse> {
	const params: Record<string, string | number> = { customer_id: customerId };
	if (objectType) params.object_type = objectType;
	return apiGet<RulesResponse>('/rules', params);
}

export function fetchHealthMetrics(customerId: number): Promise<RuleHealthMetrics> {
	return apiGet<RuleHealthMetrics>('/rules/metrics', { customer_id: customerId });
}


export async function fetchAllRules(customerId: number, objectType?: string): Promise<Rule[]> {
	const PAGE_SIZE = 200; // matches the backend's own max
	let offset = 0;
	const all: Rule[] = [];

	while (true) {
		const params: Record<string, string | number> = {
			customer_id: customerId,
			limit: PAGE_SIZE,
			offset
		};
		if (objectType) params.object_type = objectType;
		const page = await apiGet<RulesResponse>('/rules', params);
		all.push(...page.results);
		if (page.results.length < PAGE_SIZE) break; // last page reached
		offset += PAGE_SIZE;
	}

	return all;
}