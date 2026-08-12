# Graph Schema Reference (auto-generated — do not hand-edit)

## Node labels
- BuildingBlock
- Condition
- Device
- EventCategory
- LogSourceType
- MitreTactic
- MitreTechnique
- QID
- ReferenceMap
- ReferenceSet
- Rule

## Node properties
**Condition**
- condition_id: Long
- field: String
- negated: Boolean
- operator: String
- raw_text: String
- rule_id: Long
- sequence_order: Long
- test_class: String
- timeout_correlation_fields: StringArray
- timeout_time_unit: String
- timeout_time_value: Long
- values: StringArray

**Device**
- name: String

**EventCategory**
- high_level: String
- low_level: String

**LogSourceType**
- name: String

**MitreTactic**
- name: String
- tactic_id: String

**MitreTechnique**
- name: String
- technique_id: String

**QID**
- event_name: String
- qid: Long

**ReferenceMap**
- name: String

**ReferenceSet**
- name: String

**Rule**
- customer_id: Long
- enabled: Boolean
- identifier: String
- name: String
- object_type: String
- origin: String
- owner: String
- qradar_rule_id: Long
- rule_id: Long
- type: String

## Relationship types
- BELONGS_TO_TACTIC
- DEPENDS_ON_REFMAP
- DEPENDS_ON_REFSET
- DETECTS_TECHNIQUE
- FOLLOWED_BY
- HAS_CONDITION
- MATCHES_EVENT_CATEGORY
- MATCHES_QID
- REFERENCES
- REQUIRES_DEVICE
- REQUIRES_LOGSOURCE_TYPE

## Relationship properties
**BELONGS_TO_TACTIC**
- None: unknown

**DEPENDS_ON_REFMAP**
- key_field: String
- value_field: String

**DEPENDS_ON_REFSET**
- fields: StringArray
- match_mode: String

**DETECTS_TECHNIQUE**
- None: unknown

**FOLLOWED_BY**
- correlation_field: String
- customer_id: Long
- direction: String
- min_count: Long,String
- rule_id: Long
- rule_name: String
- sequence_test_class: String
- source_bb_id: String
- target_bb_id: String
- time_unit: String
- time_value: Long

**HAS_CONDITION**
- None: unknown

**MATCHES_EVENT_CATEGORY**
- None: unknown

**MATCHES_QID**
- None: unknown

**REFERENCES**
- bb_id: String
- customer_id: Long
- rule_id: Long
- threshold_cardinality_count: Long
- threshold_cardinality_field: String
- threshold_count: Long
- threshold_grouping_field: String
- threshold_operator: String
- threshold_time_unit: String
- threshold_time_value: Long

**REQUIRES_DEVICE**
- None: unknown

**REQUIRES_LOGSOURCE_TYPE**
- None: unknown

## Topology (source -> relationship -> target)
- (MitreTechnique) -[:BELONGS_TO_TACTIC]-> (MitreTactic)
- (Rule:BuildingBlock) -[:DEPENDS_ON_REFMAP]-> (ReferenceMap)
- (Rule) -[:DEPENDS_ON_REFMAP]-> (ReferenceMap)
- (Rule) -[:DEPENDS_ON_REFSET]-> (ReferenceSet)
- (Rule:BuildingBlock) -[:DEPENDS_ON_REFSET]-> (ReferenceSet)
- (Rule) -[:DETECTS_TECHNIQUE]-> (MitreTechnique)
- (Rule:BuildingBlock) -[:DETECTS_TECHNIQUE]-> (MitreTechnique)
- (Rule:BuildingBlock) -[:FOLLOWED_BY]-> (Rule:BuildingBlock)
- (Rule) -[:FOLLOWED_BY]-> (Rule:BuildingBlock)
- (Rule) -[:HAS_CONDITION]-> (Condition)
- (Rule:BuildingBlock) -[:HAS_CONDITION]-> (Condition)
- (Rule:BuildingBlock) -[:MATCHES_EVENT_CATEGORY]-> (EventCategory)
- (Rule) -[:MATCHES_EVENT_CATEGORY]-> (EventCategory)
- (Rule:BuildingBlock) -[:MATCHES_QID]-> (QID)
- (Rule) -[:MATCHES_QID]-> (QID)
- (Rule) -[:REFERENCES]-> (Rule)
- (Rule) -[:REFERENCES]-> (Rule:BuildingBlock)
- (Rule:BuildingBlock) -[:REFERENCES]-> (Rule:BuildingBlock)
- (Rule:BuildingBlock) -[:REFERENCES]-> (Rule)
- (Rule) -[:REQUIRES_DEVICE]-> (Device)
- (Rule:BuildingBlock) -[:REQUIRES_DEVICE]-> (Device)
- (Rule) -[:REQUIRES_LOGSOURCE_TYPE]-> (LogSourceType)
- (Rule:BuildingBlock) -[:REQUIRES_LOGSOURCE_TYPE]-> (LogSourceType)
