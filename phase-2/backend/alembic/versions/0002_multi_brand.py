"""Many brands per account, so any agent can serve any brand.

Revision ID: 0002_multi_brand
Revises: 0001_initial
Create Date: 2026-11-22

``0001`` put ``UNIQUE(user_id, domain)`` on ``domain_profiles`` and
``UNIQUE(user_id, agent_key)`` on ``agent_profiles``. Together those allowed one
brand per account and one configuration per agent, so working on a second
client meant overwriting the first -- and the first client's memories stayed
behind and bled into the second one's output.

This migration:

* adds ``domain_profiles.label`` (brand name shown in the switcher) and
  ``domain_profiles.is_active`` (which brand the account is working in);
* adds ``brand_profile_id`` to ``agent_profiles``, ``conversations`` and
  ``memories``;
* backfills those from each user's single existing brand, so nothing is
  orphaned and every existing setup keeps working untouched;
* replaces the two unique constraints.

Global memories (``domain IS NULL``) are deliberately left with a NULL brand:
they describe the *user*, not a client, and must keep spanning every brand.

``batch_alter_table`` is used throughout because SQLite cannot drop a
constraint in place -- batch mode rebuilds the table. It is a no-op wrapper on
PostgreSQL.
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_multi_brand"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHILDREN = ("agent_profiles", "conversations", "memories")


def _brand_label(raw: object) -> str:
    """Best-effort brand name out of the stored profile JSON.

    Read in Python rather than with ``json_extract`` / ``->>`` so the migration
    runs the same on SQLite and PostgreSQL.
    """
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return ""
    else:
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get("brand_name") or ""
    return str(value)[:160]


def upgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------------- columns
    with op.batch_alter_table("domain_profiles") as batch:
        batch.add_column(sa.Column("label", sa.String(length=160), nullable=True))
        batch.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    for table in _CHILDREN:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("brand_profile_id", sa.Uuid(as_uuid=True), nullable=True))

    # --------------------------------------------------------------- backfill
    # Every user had at most one brand per domain, so (user_id, domain) maps
    # unambiguously onto it. That is exactly the constraint being removed.
    brands = bind.execute(
        sa.text("SELECT id, user_id, domain, profile_data FROM domain_profiles")
    ).fetchall()

    for brand_id, user_id, domain, profile_data in brands:
        label = _brand_label(profile_data) or "My brand"
        bind.execute(
            sa.text(
                "UPDATE domain_profiles SET label = :label, is_active = :active WHERE id = :id"
            ),
            {"label": label, "active": True, "id": brand_id},
        )
        # Children are matched on user + domain, the pre-migration grain.
        for table in ("agent_profiles", "conversations"):
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET brand_profile_id = :brand "
                    "WHERE user_id = :user AND domain = :domain"
                ),
                {"brand": brand_id, "user": user_id, "domain": domain},
            )
        # Memories only when they are brand- or agent-scoped. A global memory
        # keeps brand_profile_id NULL so it still applies to every brand.
        bind.execute(
            sa.text(
                "UPDATE memories SET brand_profile_id = :brand "
                "WHERE user_id = :user AND domain = :domain AND domain IS NOT NULL"
            ),
            {"brand": brand_id, "user": user_id, "domain": domain},
        )

    # `label` is NOT NULL in the model; it could only be set after the backfill.
    with op.batch_alter_table("domain_profiles") as batch:
        batch.alter_column(
            "label", existing_type=sa.String(length=160), nullable=False, server_default=""
        )

    # ------------------------------------------------------------ constraints
    with op.batch_alter_table("domain_profiles") as batch:
        batch.drop_constraint("uq_domain_profiles_user_domain", type_="unique")

    with op.batch_alter_table("agent_profiles") as batch:
        batch.drop_constraint("uq_agent_profiles_user_agent", type_="unique")
        batch.create_unique_constraint(
            "uq_agent_profiles_user_brand_agent", ["user_id", "brand_profile_id", "agent_key"]
        )
        batch.create_foreign_key(
            "fk_agent_profiles_brand_profile_id_domain_profiles",
            "domain_profiles",
            ["brand_profile_id"],
            ["id"],
            ondelete="CASCADE",
        )

    for table in ("conversations", "memories"):
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                f"fk_{table}_brand_profile_id_domain_profiles",
                "domain_profiles",
                ["brand_profile_id"],
                ["id"],
                ondelete="CASCADE",
            )

    for table in _CHILDREN:
        op.create_index(
            f"ix_{table}_brand_profile_id", table, ["brand_profile_id"], unique=False
        )
    op.create_index(
        "ix_domain_profiles_user_active", "domain_profiles", ["user_id", "is_active"], unique=False
    )


def downgrade() -> None:
    """Return to one brand per account.

    Rows belonging to a non-active brand are deleted: the old schema has
    nowhere to put them, and keeping them would violate the unique constraints
    being restored. The active brand of each user is the one that survives.
    """
    bind = op.get_bind()

    extra = bind.execute(
        sa.text("SELECT id FROM domain_profiles WHERE is_active = :inactive"),
        {"inactive": False},
    ).fetchall()
    for (brand_id,) in extra:
        for table in _CHILDREN:
            bind.execute(
                sa.text(f"DELETE FROM {table} WHERE brand_profile_id = :brand"),
                {"brand": brand_id},
            )
        bind.execute(
            sa.text("DELETE FROM domain_profiles WHERE id = :brand"), {"brand": brand_id}
        )

    op.drop_index("ix_domain_profiles_user_active", table_name="domain_profiles")
    for table in _CHILDREN:
        op.drop_index(f"ix_{table}_brand_profile_id", table_name=table)

    for table in ("conversations", "memories"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(
                f"fk_{table}_brand_profile_id_domain_profiles", type_="foreignkey"
            )
            batch.drop_column("brand_profile_id")

    with op.batch_alter_table("agent_profiles") as batch:
        batch.drop_constraint(
            "fk_agent_profiles_brand_profile_id_domain_profiles", type_="foreignkey"
        )
        batch.drop_constraint("uq_agent_profiles_user_brand_agent", type_="unique")
        batch.drop_column("brand_profile_id")
        batch.create_unique_constraint("uq_agent_profiles_user_agent", ["user_id", "agent_key"])

    with op.batch_alter_table("domain_profiles") as batch:
        batch.drop_column("is_active")
        batch.drop_column("label")
        batch.create_unique_constraint("uq_domain_profiles_user_domain", ["user_id", "domain"])
