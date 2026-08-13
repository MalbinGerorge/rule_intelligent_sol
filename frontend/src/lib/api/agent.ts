import { apiPost } from './client';
import type { AgentAskResponse } from '$lib/types/agent';

export function askAgent(question: string, customerId: number): Promise<AgentAskResponse> {
	return apiPost<AgentAskResponse>('/agent/ask', { question, customer_id: customerId });
}