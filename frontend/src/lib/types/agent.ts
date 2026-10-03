export interface AgentAskResponse {
	status: 'ok' | 'needs_clarification' | 'not_answerable' | 'rejected' | 'llm_error';
	query: string | null;
	rows: Record<string, unknown>[] | null;
	retried: boolean | null;
	question: string | null; // populated when status === 'needs_clarification'
	reason: string | null;
	error: string | null;
}

export interface ChatTurn {
	role: 'user' | 'assistant';
	text: string;
	response?: AgentAskResponse;
}