import { apiGet, apiPost } from './client';

export interface RootCause {
	cause: string;
	confidence: 'high' | 'medium' | 'low';
	evidence: string[];
	next_steps: string[];
}

export interface NewRuleOpportunity {
	observation: string;
	evidence: string[];
	suggested_next_step: string;
}

export interface FinalReport {
	detection_intent: string;
	structural_summary: string;
	root_causes: RootCause[];
	overall_recommendation: string;
	additional_findings: NewRuleOpportunity[];
}

export interface ChainAnalysis {
	detection_intent: string;
	preconditions: string[];
	structural_flags: string[];
}

export interface InvestigationCreateResponse {
	id: number;
	status: string;
}

export interface InvestigationDetail {
	id: number;
	rule_id: number;
	customer_id: number;
	status: 'running' | 'completed' | 'failed';
	error: string | null;
	chain_analysis: ChainAnalysis | null;
	final_report: FinalReport | null;
	rendered_report: string | null;
	trace: string | null;
	tool_calls_made: number | null;
	created_at: string;
}

export interface InvestigationListItem {
	id: number;
	status: string;
	tool_calls_made: number | null;
	created_at: string;
}

export interface InvestigationListResponse {
	items: InvestigationListItem[];
	total: number;
	limit: number;
	offset: number;
}

export function startInvestigation(ruleId: number): Promise<InvestigationCreateResponse> {
	return apiPost(`/rule-analyzer/rules/${ruleId}/investigate`, {});
}

export function getInvestigation(investigationId: number): Promise<InvestigationDetail> {
	return apiGet(`/rule-analyzer/investigations/${investigationId}`);
}

export function listInvestigations(
	ruleId: number,
	limit = 20,
	offset = 0
): Promise<InvestigationListResponse> {
	return apiGet(`/rule-analyzer/rules/${ruleId}/investigations`, { limit, offset });
}