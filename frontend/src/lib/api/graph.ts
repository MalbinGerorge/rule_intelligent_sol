import { apiGet } from './client';
import type { BuildingBlockDependent, FieldSearchResult, RuleGraphDetail } from '$lib/types/graph';

export function searchByField(field: string, customerId: number): Promise<FieldSearchResult[]> {
	return apiGet<FieldSearchResult[]>('/graph/rules/search/by-field', {
		field,
		customer_id: customerId
	});
}

export function fetchBbDependents(
	identifier: string,
	customerId: number
): Promise<BuildingBlockDependent[]> {
	return apiGet<BuildingBlockDependent[]>(
		`/graph/building-blocks/${encodeURIComponent(identifier)}/dependents`,
		{ customer_id: customerId }
	);
}

export function fetchRuleGraph(ruleId: number): Promise<RuleGraphDetail> {
	return apiGet<RuleGraphDetail>(`/graph/rules/${ruleId}`);
}