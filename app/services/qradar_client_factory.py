"""
Constructs a QRadarClient for a given customer_id, decrypting the
saved token from customer_credentials -- same lookup pattern as
scripts/ingest.py's load_customer(), but keyed by customer_id (what
the Rule Analyzer's tools use) rather than customer name.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.qradar_client import QRadarClient


def build_qradar_client_for_customer(db: Session, customer_id: int) -> QRadarClient:
    row = db.execute(
        text(
            """
            SELECT c.qradar_host, c.verify_ssl,
                   pgp_sym_decrypt(cc.token_encrypted, :key) AS token
            FROM customers c
            JOIN customer_credentials cc ON cc.customer_id = c.id
            WHERE c.id = :customer_id
            """
        ),
        {"customer_id": customer_id, "key": settings.token_encryption_key},
    ).mappings().first()

    if row is None:
        raise ValueError(f"No customer with id {customer_id} has saved QRadar credentials.")

    return QRadarClient(host=row["qradar_host"], token=row["token"], verify_ssl=row["verify_ssl"])