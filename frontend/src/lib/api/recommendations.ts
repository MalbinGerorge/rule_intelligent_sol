import { apiGet, apiPost } from './client';
import type { MitreGap, LogSourceGap } from '$lib/types/recommendations';

export interface SigmaGenerationJobCreateResponse {
	id: number;
	status: string;
	total_rules: number;
}

export function startSigmaGeneration(customerName: string): Promise<SigmaGenerationJobCreateResponse> {
	return apiPost(`/recommendations/customers/${encodeURIComponent(customerName)}/sigma/generate`, {});
}

export function fetchMitreGaps(customerName: string): Promise<MitreGap[]> {
	return apiGet(`/recommendations/customers/${encodeURIComponent(customerName)}/mitre-gaps`);
}

export function fetchLogSourceGaps(customerName: string): Promise<LogSourceGap[]> {
	return apiGet(`/recommendations/customers/${encodeURIComponent(customerName)}/log-source-gaps`);
}