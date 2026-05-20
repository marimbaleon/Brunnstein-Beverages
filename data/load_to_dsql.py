"""DSQL-specific loading: engine with IAM auth, schema setup, batched inserts.

DSQL is Postgres-compatible but rejects a couple of standard SQLAlchemy patterns:
the empty rollback issued on first connect, FOREIGN KEY constraints in DDL,
and transactions modifying more than ~3000 rows.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

import boto3
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import ForeignKeyConstraint, MetaData


def get_engine() -> Engine:
    """Build a SQLAlchemy engine for DSQL using a fresh IAM token."""
    cluster_id = os.environ["DSQL_CLUSTER_ID"]
    region = os.environ.get("AWS_REGION", "eu-central-1")
    profile = os.environ.get("AWS_PROFILE")

    hostname = f"{cluster_id}.dsql.{region}.on.aws"

    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client("dsql")
    token = client.generate_db_connect_admin_auth_token(
        Hostname=hostname,
        Region=region,
    )

    url = (
        f"postgresql+psycopg://admin:{quote_plus(token)}@{hostname}:5432"
        "/postgres?sslmode=require"
    )
    return create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )


def strip_foreign_keys(metadata: MetaData) -> None:
    """Remove FK constraints from metadata so create_all emits DSQL-friendly DDL."""
    for table in metadata.tables.values():
        for constraint in list(table.constraints):
            if isinstance(constraint, ForeignKeyConstraint):
                table.constraints.discard(constraint)


def load_table(session: Session, items: list, chunk_size: int = 200) -> None:
    """Insert ORM instances into the session in chunks, flushing after each.

    Chunk size 200 keeps a parent batch plus its cascaded line rows comfortably
    under the DSQL ~3000-rows-per-transaction cap.
    """
    for i in range(0, len(items), chunk_size):
        session.add_all(items[i:i + chunk_size])
        session.flush()
