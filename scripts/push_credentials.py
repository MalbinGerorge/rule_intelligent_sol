"""
Insert (or update) a customer and their encrypted QRadar token.

Token is encrypted at rest using Postgres pgcrypto (pgp_sym_encrypt),
keyed by TOKEN_ENCRYPTION_KEY from .env — never stored in plaintext.

Usage:
    uv run python scripts/push_credentials.py \\
        --name cotecna \\
        --host 23.97.253.242 \\
        --token "your-qradar-token" \\
        --no-verify-ssl

Re-running with the same --name upserts (updates host/verify_ssl and
rotates the token) rather than creating a duplicate row.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine


def push_credentials(name: str, host: str, token: str, verify_ssl: bool) -> int:
    with engine.begin() as conn:
        customer_id = conn.execute(
            text(
                """
                INSERT INTO customers (name, qradar_host, verify_ssl, active)
                VALUES (:name, :host, :verify_ssl, true)
                ON CONFLICT (name) DO UPDATE
                    SET qradar_host = EXCLUDED.qradar_host,
                        verify_ssl = EXCLUDED.verify_ssl
                RETURNING id
                """
            ),
            {"name": name, "host": host, "verify_ssl": verify_ssl},
        ).scalar_one()

        conn.execute(
            text(
                """
                INSERT INTO customer_credentials (customer_id, token_encrypted)
                VALUES (:customer_id, pgp_sym_encrypt(:token, :key))
                ON CONFLICT (customer_id) DO UPDATE
                    SET token_encrypted = EXCLUDED.token_encrypted,
                        rotated_at = now()
                """
            ),
            {"customer_id": customer_id, "token": token, "key": settings.token_encryption_key},
        )

    return customer_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="customer name, e.g. cotecna")
    parser.add_argument("--host", required=True, help="QRadar console host/IP")
    parser.add_argument("--token", required=True, help="QRadar SEC token")
    parser.add_argument(
        "--verify-ssl", dest="verify_ssl", action="store_true", default=False,
        help="verify the console's TLS cert (off by default — most consoles use self-signed certs)",
    )
    args = parser.parse_args()

    customer_id = push_credentials(args.name, args.host, args.token, args.verify_ssl)
    print(f"OK: customer '{args.name}' (id={customer_id}) credentials stored/updated.")


if __name__ == "__main__":
    main()