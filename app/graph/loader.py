"""
Loads the graph for one customer into Neo4j, from Postgres data that's
already been parsed and tested (rules, rule_building_blocks,
rule_conditions, mitre_mappings).

Approach: full rebuild per customer, not incremental. Clear this
customer's slice of the graph, then reload everything fresh from
Postgres. Simpler correctness story than mirroring Postgres's
needs_reparse incremental logic in Cypher too, and at ~1,152 rows this
runs in well under a second — not worth the extra complexity yet.

Node labels:
    (:Rule)               -- every rule and BB (object_type distinguishes)
    (:Rule:BuildingBlock)  -- extra label added when object_type = BUILDING_BLOCK
    (:Condition)           -- one per rule_conditions row, EXCEPT
                               ThresholdFunction_Test (data moved onto
                               REFERENCES edges), DeviceTypeID_Test (data
                               moved onto LogSourceType), and DeviceID_Test
                               (data moved onto Device) — all three would
                               otherwise create a redundant, mostly-null
                               node duplicating data with a proper home
                               elsewhere
    (:LogSourceType)       -- a CATEGORY (e.g. "Microsoft Windows Security
                               Event Log"), from DeviceTypeID_Test
    (:Device)              -- a SPECIFIC CONFIGURED INSTANCE (e.g. "Custom
                               Rule Engine-8 :: c-ctcna-qr"), from
                               DeviceID_Test. Deliberately separate from
                               LogSourceType: "rules needing any Windows
                               log source" and "rules needing this one
                               specific device" are different questions.
    (:MitreTechnique)
    (:MitreTactic)

Relationships:
    (:Rule)-[:REFERENCES {threshold_count, threshold_operator,
        threshold_grouping_field, threshold_cardinality_count,
        threshold_cardinality_field, threshold_time_value,
        threshold_time_unit}]->(:Rule:BuildingBlock)
        -- threshold_* properties present only when a ThresholdFunction_Test
           condition named this specific BB; absent for plain references
    (:Rule)-[:HAS_CONDITION]->(:Condition)
    (:Rule)-[:REQUIRES_LOGSOURCE_TYPE]->(:LogSourceType)
    (:Rule)-[:REQUIRES_DEVICE]->(:Device)
    (:Rule)-[:DETECTS_TECHNIQUE]->(:MitreTechnique)
    (:MitreTechnique)-[:BELONGS_TO_TACTIC]->(:MitreTactic)
"""
from __future__ import annotations

from neo4j import Driver
from sqlalchemy import text
from sqlalchemy.orm import Session


def clear_customer_graph(driver: Driver, customer_id: int) -> None:
    """Removes every node belonging to this customer (and, via DETACH
    DELETE, every relationship touching them) before a fresh reload.
    Shared/reusable nodes (LogSourceType, Device, EventCategory, QID,
    ReferenceSet, ReferenceMap, MitreTechnique, MitreTactic) aren't
    customer-scoped in their MERGE key -- same as MitreTechnique always
    was -- so they're only removed if nothing references them anymore
    (orphan check), not deleted outright, since another customer's rule
    could legitimately still depend on the same shared entity.
    Condition nodes are NEVER shared (CREATEd fresh per rule, not
    MERGEd) -- once their parent Rule is gone they're always garbage,
    so they're included in the same orphan sweep.

    BUG FIX: earlier versions of this function only cleaned up orphaned
    MitreTechnique/MitreTactic nodes -- every other shared node type
    added since then was being left behind as an orphan on every single
    rebuild. Confirmed via a real orphan-count query showing
    accumulation across multiple build_graph.py runs.
    """
    with driver.session() as session:
        session.run(
            "MATCH (r:Rule {customer_id: $customer_id}) DETACH DELETE r",
            customer_id=customer_id,
        )
        session.run(
            """
            MATCH (n)
            WHERE (n:MitreTechnique OR n:MitreTactic OR n:LogSourceType
                   OR n:Device OR n:EventCategory OR n:QID
                   OR n:ReferenceSet OR n:ReferenceMap OR n:Condition)
              AND NOT (n)--()
            DELETE n
            """
        )


def _load_rule_nodes(driver: Driver, db: Session, customer_id: int) -> int:
    rows = db.execute(
        text(
            """
            SELECT r.id AS rule_id, r.customer_id, r.qradar_rule_id, r.identifier, r.name,
                   r.object_type, r.type, r.enabled, r.owner, r.origin, r.created_at, r.updated_at,
                   resp.force_offense_creation, resp.offense_mapping, resp.severity,
                   resp.credibility, resp.relevance, resp.qid AS dispatch_qid,
                   resp.low_level_category, resp.event_name AS dispatch_event_name,
                   resp.describe_offense, resp.override_offense_name, resp.contribute_offense_name,
                   resp.limiter_response_count, resp.limiter_interval_count,
                   resp.limiter_interval_type, resp.limiter_host_type
            FROM rules r
            LEFT JOIN rule_responses resp ON resp.rule_id = r.id
            WHERE r.customer_id = :c
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MERGE (r:Rule {rule_id: row.rule_id})
            SET r.customer_id = row.customer_id,
                r.qradar_rule_id = row.qradar_rule_id,
                r.identifier = row.identifier,
                r.name = row.name,
                r.object_type = row.object_type,
                r.type = row.type,
                r.enabled = row.enabled,
                r.owner = row.owner,
                r.origin = row.origin,
                r.created_at = row.created_at,
                r.updated_at = row.updated_at,
                r.force_offense_creation = row.force_offense_creation,
                r.offense_mapping = row.offense_mapping,
                r.dispatch_severity = row.severity,
                r.dispatch_credibility = row.credibility,
                r.dispatch_relevance = row.relevance,
                r.dispatch_qid = row.dispatch_qid,
                r.dispatch_low_level_category = row.low_level_category,
                r.dispatch_event_name = row.dispatch_event_name,
                r.describe_offense = row.describe_offense,
                r.override_offense_name = row.override_offense_name,
                r.contribute_offense_name = row.contribute_offense_name,
                r.limiter_response_count = row.limiter_response_count,
                r.limiter_interval_count = row.limiter_interval_count,
                r.limiter_interval_type = row.limiter_interval_type,
                r.limiter_host_type = row.limiter_host_type
            WITH r, row
            FOREACH (_ IN CASE WHEN row.object_type = 'BUILDING_BLOCK' THEN [1] ELSE [] END |
                SET r:BuildingBlock
            )
            """,
            rows=[dict(r) for r in rows],
        )
    return len(rows)


def _load_bb_reference_edges(driver: Driver, db: Session, customer_id: int) -> int:
    # bb_id on rule_building_blocks is the referenced BB's identifier
    # string (e.g. SYSTEM-1300), so we match the target by identifier,
    # not by Postgres id.
    rows = db.execute(
        text(
            """
            SELECT rbb.rule_id, r.customer_id, rbb.bb_id
            FROM rule_building_blocks rbb
            JOIN rules r ON r.id = rbb.rule_id
            WHERE r.customer_id = :c
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    # ThresholdFunction_Test conditions carry per-(rule, bb) threshold
    # data — merge it onto the matching REFERENCES edge instead of a
    # separate Condition node. A rule can have MULTIPLE
    # ThresholdFunction_Test entries (rare but real), each naming its own
    # bb_ids, so we key by (rule_id, bb_id) pair, not just rule_id.
    threshold_rows = db.execute(
        text(
            """
            SELECT rc.rule_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'ThresholdFunction_Test'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    threshold_by_pair: dict[tuple[int, str], dict] = {}
    for t in threshold_rows:
        threshold = t["structured_data"].get("threshold")
        if not threshold:
            continue
        for bb_id in threshold.get("bb_ids", []):
            threshold_by_pair[(t["rule_id"], bb_id)] = threshold

    prepared = []
    for r in rows:
        row = dict(r)
        threshold = threshold_by_pair.get((row["rule_id"], row["bb_id"]))
        if threshold:
            row["threshold_count"] = threshold.get("count")
            row["threshold_operator"] = threshold.get("operator")
            row["threshold_grouping_field"] = threshold.get("grouping_field")
            row["threshold_cardinality_count"] = threshold.get("cardinality_count")
            row["threshold_cardinality_field"] = threshold.get("cardinality_field")
            row["threshold_time_value"] = threshold.get("time_value")
            row["threshold_time_unit"] = threshold.get("time_unit")
        prepared.append(row)

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MATCH (bb:Rule {identifier: row.bb_id, customer_id: row.customer_id})
            MERGE (r)-[rel:REFERENCES]->(bb)
            SET rel += row
            """,
            rows=prepared,
        )
    return len(rows)


def _load_condition_nodes(driver: Driver, db: Session, customer_id: int) -> int:
    rows = db.execute(
        text(
            """
            SELECT rc.id AS condition_id, rc.rule_id, rc.sequence_order,
                   rc.test_class, rc.negated, rc.raw_text, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c
              AND rc.test_class NOT IN (
                  'ThresholdFunction_Test', 'DeviceTypeID_Test', 'DeviceID_Test',
                  'SequenceFunction_Test', 'DoubleSequenceFunction_Test','QID_Test','RuleMatch_Test',
                  'CauseAndEffect_Test', 'TriggerMatchCount','EventCategory_Test','ReferenceSetTest','ReferenceDataTest'
              )
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        row = dict(r)
        structured = row.pop("structured_data") or {}

        # Promote whatever this condition's shape actually has into real,
        # queryable properties — not everything ends up on every node,
        # since different test classes produce different shapes.
        row["field"] = structured.get("field")
        row["operator"] = structured.get("operator")
        row["values"] = structured.get("values")

        threshold = structured.get("threshold")
        if threshold:
            row["threshold_count"] = threshold.get("count")
            row["threshold_operator"] = threshold.get("operator")
            row["threshold_grouping_field"] = threshold.get("grouping_field")
            row["threshold_cardinality_count"] = threshold.get("cardinality_count")
            row["threshold_cardinality_field"] = threshold.get("cardinality_field")
            row["threshold_time_value"] = threshold.get("time_value")
            row["threshold_time_unit"] = threshold.get("time_unit")

        timeout = structured.get("timeout")
        if timeout:
            row["timeout_time_value"] = timeout.get("time_value")
            row["timeout_time_unit"] = timeout.get("time_unit")
            row["timeout_correlation_fields"] = timeout.get("correlation_fields")

        prepared.append(row)

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            CREATE (c:Condition)
            SET c = row
            MERGE (r)-[:HAS_CONDITION]->(c)
            """,
            rows=prepared,
        )
    return len(rows)


def _load_logsource_type_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    LogSourceType nodes from DeviceTypeID_Test conditions — represents a
    CATEGORY (e.g. "Microsoft Windows Security Event Log"), not a
    specific configured instance. See _load_device_edges for the
    distinct, more specific concept (DeviceID_Test).
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id, r.customer_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'DeviceTypeID_Test'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        device_type = r["structured_data"].get("device_type")
        names = device_type.get("log_source_names", []) if device_type else []
        for name in names:
            prepared.append({"rule_id": r["rule_id"], "customer_id": r["customer_id"], "name": name})

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (lst:LogSourceType {name: row.name})
            MERGE (r)-[:REQUIRES_LOGSOURCE_TYPE]->(lst)
            """,
            rows=prepared,
        )
    return len(prepared)


def _load_followed_by_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    Builds FOLLOWED_BY edges directly between the two BBs (or rules)
    named by each of the 4 sequence/chain test classes — instead of a
    disconnected Condition node that merely MENTIONS them. Same
    "sticky note -> real arrow" fix as the ThresholdFunction_Test
    refactor, applied to sequence relationships.

    OPTION C (deliberate choice — see project notes): rule_id is part
    of the MERGE key, not just a property. If two different rules both
    describe the same BB-A -> BB-B pair with DIFFERENT timing, this
    creates TWO separate edges (one per rule), not one shared edge that
    would silently overwrite one rule's timing with another's. Confirmed
    from real data this genuinely happens (57 raw pairs, 32 distinct
    BB-pairs — meaning several rules already share the same pair).

    Pair-generation differs per class (see rule_condition_parser.py
    for the confirmed shapes):
      - SequenceFunction_Test: ORDERED CHAIN — consecutive pairs
        (bb[0]->bb[1], bb[1]->bb[2], ...), since it can have more than 2 BBs
      - DoubleSequenceFunction_Test / CauseAndEffect_Test / TriggerMatchCount:
        fixed 2-stage — cross product of stage-1 BBs x stage-2 BBs
        (every real sample seen has exactly 1 BB per stage, but the
        cross product handles multi-BB stages correctly too)
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id AS source_rule_id, r.name AS source_rule_name,
                   rc.test_class, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c
              AND rc.test_class IN ('SequenceFunction_Test', 'DoubleSequenceFunction_Test',
                                     'CauseAndEffect_Test', 'TriggerMatchCount')
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        test_class = r["test_class"]
        data = r["structured_data"]
        base = {
            "customer_id": customer_id,
            "rule_id": r["source_rule_id"],
            "rule_name": r["source_rule_name"],
            "sequence_test_class": test_class,
        }

        if test_class == "SequenceFunction_Test":
            seq = data.get("sequence")
            if not seq:
                continue
            bb_ids = seq.get("bb_ids", [])
            for i in range(len(bb_ids) - 1):
                prepared.append({
                    **base,
                    "source_bb_id": bb_ids[i],
                    "target_bb_id": bb_ids[i + 1],
                    "min_count": seq.get("min_count"),
                    "correlation_field": seq.get("correlation_field_a"),
                    "time_value": seq.get("time_value"),
                    "time_unit": seq.get("time_unit"),
                })

        elif test_class == "DoubleSequenceFunction_Test":
            dseq = data.get("double_sequence")
            if not dseq:
                continue
            for src in dseq.get("stage1_bb_ids", []):
                for tgt in dseq.get("stage2_bb_ids", []):
                    prepared.append({
                        **base,
                        "source_bb_id": src,
                        "target_bb_id": tgt,
                        "min_count": dseq.get("stage2_min_count"),
                        "correlation_field": dseq.get("stage2_correlation_field"),
                        "time_value": dseq.get("time_value"),
                        "time_unit": dseq.get("time_unit"),
                        "direction": dseq.get("direction"),
                    })

        elif test_class == "CauseAndEffect_Test":
            cae = data.get("cause_and_effect")
            if not cae:
                continue
            side = cae.get("stage2_field_side") or ""
            ftype = cae.get("stage2_field_type") or ""
            combined_field = f"{side} {ftype}".strip() or None
            for src in cae.get("stage1_bb_ids", []):
                for tgt in cae.get("stage2_bb_ids", []):
                    prepared.append({
                        **base,
                        "source_bb_id": src,
                        "target_bb_id": tgt,
                        "min_count": cae.get("stage2_min_count"),
                        "correlation_field": combined_field,
                        "time_value": cae.get("time_value"),
                        "time_unit": cae.get("time_unit"),
                    })

        elif test_class == "TriggerMatchCount":
            tmc = data.get("trigger_match_count")
            if not tmc:
                continue
            for src in tmc.get("trigger_bb_ids", []):
                for tgt in tmc.get("later_bb_ids", []):
                    prepared.append({
                        **base,
                        "source_bb_id": src,
                        "target_bb_id": tgt,
                        "min_count": tmc.get("later_min_count"),
                        "correlation_field": tmc.get("correlation_field"),
                        "time_value": tmc.get("time_value"),
                        "time_unit": tmc.get("time_unit"),
                    })

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (a:Rule {identifier: row.source_bb_id, customer_id: row.customer_id})
            MATCH (b:Rule {identifier: row.target_bb_id, customer_id: row.customer_id})
            MERGE (a)-[rel:FOLLOWED_BY {rule_id: row.rule_id}]->(b)
            SET rel += row
            """,
            rows=prepared,
        )
    return len(prepared)


def _load_device_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    Device nodes from DeviceID_Test conditions — a specific configured
    log source instance (e.g. "Custom Rule Engine-8 :: c-ctcna-qr"),
    NOT the same concept as LogSourceType (a category/type, e.g.
    "Microsoft Windows Security Event Log"). Kept as a separate node
    type deliberately: "rules needing any Windows log source" and
    "rules needing this one specific configured device" are genuinely
    different questions.
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id, r.customer_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'DeviceID_Test'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        device_id = r["structured_data"].get("device_id")
        names = device_id.get("device_names", []) if device_id else []
        for name in names:
            prepared.append({"rule_id": r["rule_id"], "customer_id": r["customer_id"], "name": name})

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (d:Device {name: row.name})
            MERGE (r)-[:REQUIRES_DEVICE]->(d)
            """,
            rows=prepared,
        )
    return len(prepared)


def _load_event_category_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    EventCategory nodes from EventCategory_Test conditions — matched by
    (high_level, low_level) pair, since low-level names alone aren't
    unique across different high-level categories. Answers "which rules
    fire on this category" as a direct query.
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id, r.customer_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'EventCategory_Test'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        ec = r["structured_data"].get("event_category")
        cats = ec.get("categories", []) if ec else []
        for cat in cats:
            prepared.append({
                "rule_id": r["rule_id"],
                "customer_id": r["customer_id"],
                "high_level": cat.get("high_level"),
                "low_level": cat.get("low_level") or "",
            })

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (ec:EventCategory {high_level: row.high_level, low_level: row.low_level})
            MERGE (r)-[:MATCHES_EVENT_CATEGORY]->(ec)
            """,
            rows=prepared,
        )
    return len(prepared)


def _load_qid_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    QID nodes from QID_Test conditions — matched on the numeric QID
    itself (globally unique, unlike event category names), with
    event_name as a property. No external reference table or QRadar API
    call needed — confirmed from real data that <text> already resolves
    "(QID) Event Name" pairs directly.
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id, r.customer_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'QID_Test'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        qid_data = r["structured_data"].get("qid")
        qids = qid_data.get("qids", []) if qid_data else []
        for q in qids:
            prepared.append({
                "rule_id": r["rule_id"],
                "customer_id": r["customer_id"],
                "qid": q.get("qid"),
                "event_name": q.get("event_name"),
            })

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (q:QID {qid: row.qid})
            SET q.event_name = row.event_name
            MERGE (r)-[:MATCHES_QID]->(q)
            """,
            rows=prepared,
        )
    return len(prepared)


def _load_refset_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    ReferenceSet nodes from ReferenceSetTest conditions — structural
    identity ONLY (which rule depends on which set, via which field(s)).
    Deliberately NOT the set's live contents — those are genuinely
    dynamic operational data (SOAR playbooks can update them hourly),
    resolved live via QRadar's reference-data API on-demand for UI3/UI4
    validation, never cached here. See project notes for the reasoning.
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id, r.customer_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'ReferenceSetTest'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        refset = r["structured_data"].get("refset")
        if not refset:
            continue
        for name in refset.get("refset_names", []):
            prepared.append({
                "rule_id": r["rule_id"],
                "customer_id": r["customer_id"],
                "name": name,
                "fields": refset.get("fields", []),
                "match_mode": refset.get("refset_match_mode"),
            })

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (rs:ReferenceSet {name: row.name})
            MERGE (r)-[rel:DEPENDS_ON_REFSET]->(rs)
            SET rel.fields = row.fields, rel.match_mode = row.match_mode
            """,
            rows=prepared,
        )
    return len(prepared)


def _load_refmap_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    ReferenceMap nodes from ReferenceDataTest conditions — MAP shape
    only (key+value), the only shape confirmed from real data so far.
    Same structural-identity-only principle as _load_refset_edges —
    contents are never cached here.
    """
    rows = db.execute(
        text(
            """
            SELECT rc.rule_id, r.customer_id, rc.structured_data
            FROM rule_conditions rc
            JOIN rules r ON r.id = rc.rule_id
            WHERE r.customer_id = :c AND rc.test_class = 'ReferenceDataTest'
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    prepared = []
    for r in rows:
        refmap = r["structured_data"].get("refmap")
        if not refmap:
            continue
        for name in refmap.get("map_names", []):
            prepared.append({
                "rule_id": r["rule_id"],
                "customer_id": r["customer_id"],
                "name": name,
                "key_field": refmap.get("key_field"),
                "value_field": refmap.get("value_field"),
            })

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (rm:ReferenceMap {name: row.name})
            MERGE (r)-[rel:DEPENDS_ON_REFMAP]->(rm)
            SET rel.key_field = row.key_field, rel.value_field = row.value_field
            """,
            rows=prepared,
        )
    return len(prepared)



def _load_reference_write_edges(driver: Driver, db: Session, customer_id: int) -> int:
    """
    (:Rule)-[:WRITES_TO_REFDATA]->(:ReferenceData) -- the OPPOSITE
    direction from DEPENDS_ON_REFSET/DEPENDS_ON_REFMAP (which mean
    "reads from"). Confirmed rare from real data (4 of 1152 rules) but
    real -- a rule populating a reference set/map/table as a side
    effect for OTHER rules to later read from.

    Single node label (ReferenceData) covering map/mapOfSets/
    mapOfMaps/table uniformly, with write_type as an edge property --
    deliberately not 4 separate node types, since real data so far
    only confirms ONE sub-type (referenceMapOfSets); inventing
    speculative node types for sub-types never actually observed would
    be guessing, not building from confirmed data.
    """
    rows = db.execute(
        text(
            """
            SELECT resp.rule_id, r.customer_id, resp.ref_write_target_name,
                   resp.ref_write_key_field, resp.ref_write_filter, resp.ref_write_type
            FROM rule_responses resp
            JOIN rules r ON r.id = resp.rule_id
            WHERE r.customer_id = :c AND resp.ref_write_target_name IS NOT NULL
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (rd:ReferenceData {name: row.ref_write_target_name})
            MERGE (r)-[rel:WRITES_TO_REFDATA]->(rd)
            SET rel.key_field = row.ref_write_key_field,
                rel.filter = row.ref_write_filter,
                rel.write_type = row.ref_write_type
            """,
            rows=[dict(r) for r in rows],
        )
    return len(rows)



def _load_mitre_edges(driver: Driver, db: Session, customer_id: int) -> int:
    rows = db.execute(
        text(
            """
            SELECT mm.rule_id, mm.tactic_id, mm.tactic, mm.technique_id, mm.technique_name
            FROM mitre_mappings mm
            JOIN rules r ON r.id = mm.rule_id
            WHERE r.customer_id = :c AND mm.technique_id IS NOT NULL AND mm.technique_id != ''
            """
        ),
        {"c": customer_id},
    ).mappings().all()

    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (r:Rule {rule_id: row.rule_id})
            MERGE (tech:MitreTechnique {technique_id: row.technique_id})
            SET tech.name = row.technique_name
            MERGE (r)-[:DETECTS_TECHNIQUE]->(tech)
            WITH tech, row
            FOREACH (_ IN CASE WHEN row.tactic_id IS NOT NULL AND row.tactic_id <> '' THEN [1] ELSE [] END |
                MERGE (tac:MitreTactic {tactic_id: row.tactic_id})
                SET tac.name = row.tactic
                MERGE (tech)-[:BELONGS_TO_TACTIC]->(tac)
            )
            """,
            rows=[dict(r) for r in rows],
        )
    return len(rows)


def build_customer_graph(driver: Driver, db: Session, customer_id: int) -> dict:
    """Full rebuild: clear this customer's graph, then reload everything
    fresh from Postgres. Returns counts for each piece loaded."""
    clear_customer_graph(driver, customer_id)

    rule_count = _load_rule_nodes(driver, db, customer_id)
    ref_count = _load_bb_reference_edges(driver, db, customer_id)
    condition_count = _load_condition_nodes(driver, db, customer_id)
    logsource_type_count = _load_logsource_type_edges(driver, db, customer_id)
    device_count = _load_device_edges(driver, db, customer_id)
    event_category_count = _load_event_category_edges(driver, db, customer_id)
    qid_count = _load_qid_edges(driver, db, customer_id)
    refset_count = _load_refset_edges(driver, db, customer_id)
    refmap_count = _load_refmap_edges(driver, db, customer_id)
    followed_by_count = _load_followed_by_edges(driver, db, customer_id)
    mitre_count = _load_mitre_edges(driver, db, customer_id)
    refwrite_count = _load_reference_write_edges(driver, db, customer_id)


    return {
        "rule_nodes": rule_count,
        "reference_edges": ref_count,
        "condition_nodes": condition_count,
        "logsource_type_edges": logsource_type_count,
        "device_edges": device_count,
        "event_category_edges": event_category_count,
        "qid_edges": qid_count,
        "refset_edges": refset_count,
        "refmap_edges": refmap_count,
        "followed_by_edges": followed_by_count,
        "mitre_edges": mitre_count,
        "refwrite_edges": refwrite_count,
    }