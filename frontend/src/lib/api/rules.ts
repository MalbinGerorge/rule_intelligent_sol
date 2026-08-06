import { apiGet } from './client';
import type { RulesResponse, RuleHealthMetrics } from '$lib/types/rule';

export function fetchRules(customerId: number, objectType?: string): Promise<RulesResponse> {
	const params: Record<string, string | number> = { customer_id: customerId };
	if (objectType) params.object_type = objectType;
	return apiGet<RulesResponse>('/rules', params);
}

export function fetchHealthMetrics(customerId: number): Promise<RuleHealthMetrics> {
	return apiGet<RuleHealthMetrics>('/rules/metrics', { customer_id: customerId });
}