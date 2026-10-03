import { apiGet, apiPost } from './client';
import type { MitreGap, LogSourceGap, PeerRuleSuggestion } from '$lib/types/recommendations';

export interface SigmaGenerationJobCreateResponse {
	id: number;
	status: string;
	total_rules: number;
}

export interface SigmaGenerationJobDetail {
	id: number;
	customer_id: number;
	status: string;
	requested_rule_names: string[] | null;
	total_rules: number;
	processed_rules: number;
	failed_rules: number;
	failed_rule_details: Record<string, unknown>[] | null;
	error: string | null;
	created_at: string;
	finished_at: string | null;
}

export function startSigmaGeneration(customerName: string): Promise<SigmaGenerationJobCreateResponse> {
	return apiPost(`/recommendations/customers/${encodeURIComponent(customerName)}/sigma/generate`, {});
}

export function fetchSigmaJob(jobId: number): Promise<SigmaGenerationJobDetail> {
	return apiGet(`/recommendations/sigma-jobs/${jobId}`);
}

export function fetchMitreGaps(customerName: string): Promise<MitreGap[]> {
	return apiGet(`/recommendations/customers/${encodeURIComponent(customerName)}/mitre-gaps`);
}

export function fetchLogSourceGaps(customerName: string): Promise<LogSourceGap[]> {
	return apiGet(`/recommendations/customers/${encodeURIComponent(customerName)}/log-source-gaps`);
}

export interface EmbeddingJobCreateResponse {
	id: number;
	status: string;
	total_representations: number;
}

export interface EmbeddingJobDetail {
	id: number;
	status: string;
	total_representations: number;
	processed_representations: number;
	failed_representations: number;
	error: string | null;
}

export function startEmbeddingGeneration(): Promise<EmbeddingJobCreateResponse> {
	return apiPost('/recommendations/embeddings/generate', {});
}

export function fetchEmbeddingJob(jobId: number): Promise<EmbeddingJobDetail> {
	return apiGet(`/recommendations/embeddings-jobs/${jobId}`);
}

export interface SimilaritySearchResult {
	results: PeerRuleSuggestion[];
	excluded_low_relevance: number;
}

export function searchByIntent(customerName: string, query: string): Promise<SimilaritySearchResult> {
	return apiPost(`/recommendations/customers/${encodeURIComponent(customerName)}/similarity-search`, { query });
}