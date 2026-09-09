export interface PeerRuleSuggestion {
	source_customer_name: string;
	rule_id: number;
	title: string;
	description: string | null;
	level: string | null;
	detection: Record<string, unknown>;
	tags: string[];
	mitre_source: string | null;
	mitre_confidence: string | null;
	required_log_source_types: string[];
	customer_has_required_log_source: boolean;
}

export interface MitreGap {
	technique_id: string;
	technique_name: string | null;
	tactic_names: string[];
	is_subtechnique: boolean;
	peer_customer_names: string[];
	suggested_rules: PeerRuleSuggestion[];
}

export interface LogSourceGap {
	log_source_type_name: string;
	qradar_type_id: number;
	peer_customer_names: string[];
	suggested_rules: PeerRuleSuggestion[];
}