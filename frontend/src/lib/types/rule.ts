export interface Rule {
	id: number;
	customer_id: number;
	qradar_rule_id: number;
	identifier: string | null;
	name: string | null;
	object_type: 'RULE' | 'BUILDING_BLOCK';
	building_block_subtype: string | null;
	type: string | null;
	enabled: boolean | null;
	owner: string | null;
	origin: string | null;
	created_at: string | null;
	updated_at: string | null;
	last_event_at: string | null;
	last_event_count: number | null;
	last_offense_id: string | null;
	tactics: string[];
	techniques: string[];
	sub_techniques: string[];
}

export interface RulesResponse {
	count: number;
	results: Rule[];
}

export interface RuleHealthMetrics {
	total_rules: number;
	total_building_blocks: number;
	enabled_rules: number;
	disabled_rules: number;
	enabled_triggered: number;
	enabled_not_triggered: number;
}