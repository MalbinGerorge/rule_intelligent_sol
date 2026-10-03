export interface FieldSearchResult {
	rule_id: number;
	identifier: string | null;
	name: string | null;
	operator: string | null;
	values: string[] | null;
}

export interface BuildingBlockDependent {
	rule_id: number;
	identifier: string | null;
	name: string | null;
	threshold: Record<string, unknown>;
}

export interface RuleGraphDetail {
	rule: {
		rule_id: number;
		identifier: string | null;
		name: string | null;
		object_type: string | null;
		enabled: boolean | null;
		type: string | null;
		owner: string | null;
		origin: string | null;
	};
	references: {
		identifier: string | null;
		name: string | null;
		threshold: Record<string, unknown>;
	}[];
	conditions: {
		test_class: string;
		negated: boolean;
		raw_text: string | null;
		field?: string | null;
		operator?: string | null;
		values?: string[] | null;
	}[];
	log_sources: string[];
	mitre: {
		technique_id: string | null;
		technique_name: string | null;
		tactic_id: string | null;
		tactic_name: string | null;
	}[];
	followed_by: {
		source_identifier: string | null;
		source_name: string | null;
		target_identifier: string | null;
		target_name: string | null;
		relationship: Record<string, unknown>;
	}[];
}