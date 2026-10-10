"""Refresh the MITRE ATT&CK catalog (mitre_tactics, mitre_technique_catalog)
from MITRE's published STIX bundle (enterprise-attack.json).

Every technique MITRE publishes is kept, with its status:
  active      current technique
  deprecated  retired without a replacement
  revoked     replaced by another technique (replaced_by_technique_id),
              e.g. T1562 "Impair Defenses" -> T1685 in ATT&CK v19
QRadar still maps rules to some revoked IDs, so they must stay resolvable;
readers that want the current catalog filter on status = 'active'.

Tactic names come from MITRE's own tactic objects (TA0005 is "Stealth" in
v19), not from a hard-coded mapping.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = structlog.get_logger(__name__)

MITRE_ATTACK = "mitre-attack"


def _attack_id(obj: dict) -> str | None:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == MITRE_ATTACK:
            return ref.get("external_id")
    return None


def _status(obj: dict) -> str:
    if obj.get("revoked"):
        return "revoked"
    if obj.get("x_mitre_deprecated"):
        return "deprecated"
    return "active"


def parse_attack_bundle(bundle: dict) -> tuple[list[dict], list[dict]]:
    """(tactics, techniques) from a STIX bundle. Pure: no I/O."""
    objects = bundle.get("objects", [])

    tactics = []
    tactic_name_by_shortname: dict[str, str] = {}
    for obj in objects:
        if obj.get("type") != "x-mitre-tactic" or _status(obj) != "active":
            continue
        tactic_id = _attack_id(obj)
        if tactic_id:
            tactics.append(
                {"tactic_id": tactic_id, "name": obj["name"], "shortname": obj["x_mitre_shortname"]}
            )
            tactic_name_by_shortname[obj["x_mitre_shortname"]] = obj["name"]

    attack_id_by_stix_id = {
        obj["id"]: _attack_id(obj) for obj in objects if obj.get("type") == "attack-pattern"
    }
    replaced_by_stix_id = {
        rel["source_ref"]: rel["target_ref"]
        for rel in objects
        if rel.get("type") == "relationship" and rel.get("relationship_type") == "revoked-by"
    }

    techniques: dict[str, dict] = {}
    for obj in objects:
        if obj.get("type") != "attack-pattern":
            continue
        technique_id = _attack_id(obj)
        if not technique_id:
            continue
        status = _status(obj)
        tactic_names = []
        for phase in obj.get("kill_chain_phases", []):
            if phase.get("kill_chain_name") != MITRE_ATTACK:
                continue
            name = tactic_name_by_shortname.get(phase.get("phase_name"))
            if name is None:
                logger.warning(
                    "mitre_unknown_tactic_phase",
                    technique_id=technique_id,
                    phase=phase.get("phase_name"),
                )
                continue
            tactic_names.append(name)
        is_subtechnique = bool(obj.get("x_mitre_is_subtechnique", False))
        row = {
            "technique_id": technique_id,
            "technique_name": obj.get("name"),
            "tactic_names": tactic_names,
            "is_subtechnique": is_subtechnique,
            "parent_technique_id": technique_id.split(".")[0] if is_subtechnique else None,
            "status": status,
            "replaced_by_technique_id": (
                attack_id_by_stix_id.get(replaced_by_stix_id.get(obj["id"]))
                if status == "revoked"
                else None
            ),
        }
        existing = techniques.get(technique_id)
        # The same ATT&CK ID can appear on more than one STIX object across
        # versions; the active one wins.
        if existing is None or (existing["status"] != "active" and status == "active"):
            techniques[technique_id] = row

    for row in techniques.values():
        if row["replaced_by_technique_id"] not in (None, *techniques):
            row["replaced_by_technique_id"] = None  # replacement not published as a technique
    return tactics, sorted(techniques.values(), key=lambda r: r["technique_id"])


def sync_mitre_catalog(engine: Engine, bundle: dict) -> dict:
    """Replace the catalog with the bundle's contents in one transaction."""
    tactics, techniques = parse_attack_bundle(bundle)
    if not tactics or not techniques:
        raise ValueError("MITRE bundle has no tactics or techniques; refusing to empty the catalog")

    with engine.begin() as db:
        db.execute(text("DELETE FROM mitre_tactics"))
        for tactic in tactics:
            db.execute(
                text(
                    "INSERT INTO mitre_tactics (tactic_id, name, shortname) VALUES (:tactic_id, :name, :shortname)"
                ),
                tactic,
            )

        db.execute(text("TRUNCATE TABLE mitre_technique_catalog"))
        for row in techniques:
            db.execute(
                text(
                    """
                    INSERT INTO mitre_technique_catalog
                        (technique_id, technique_name, tactic_names, is_subtechnique, parent_technique_id, status)
                    VALUES
                        (:technique_id, :technique_name, :tactic_names, :is_subtechnique, :parent_technique_id, :status)
                    """
                ),
                row,
            )
        # Second pass: every replacement now exists, so the self foreign key holds.
        for row in techniques:
            if row["replaced_by_technique_id"]:
                db.execute(
                    text(
                        "UPDATE mitre_technique_catalog SET replaced_by_technique_id = :replaced_by "
                        "WHERE technique_id = :technique_id"
                    ),
                    {
                        "replaced_by": row["replaced_by_technique_id"],
                        "technique_id": row["technique_id"],
                    },
                )

    counts = {"tactics": len(tactics)}
    for status in ("active", "deprecated", "revoked"):
        counts[status] = sum(1 for r in techniques if r["status"] == status)
    counts["revoked_with_replacement"] = sum(1 for r in techniques if r["replaced_by_technique_id"])
    return counts
