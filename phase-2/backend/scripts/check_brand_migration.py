#!/usr/bin/env python3
"""Verify the 0002 multi-brand migration on a copy of a real database.

Asserts the backfill left nothing orphaned and that the scope rules hold:
brand- and agent-scoped memories belong to exactly one brand, global memories
belong to none so they still span every brand.

    python scripts/check_brand_migration.py /tmp/mig_test.db
"""

from __future__ import annotations

import sqlite3
import sys

PASS = 0
FAIL = 0


def check(label: str, got, want) -> None:
    global PASS, FAIL
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
    if ok:
        PASS += 1
    else:
        FAIL += 1


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mig_test.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row

    def one(sql: str, **params):
        return con.execute(sql, params).fetchone()[0]

    print(f"\nDatabase: {path}")

    print("\n1. Brands are labelled and exactly one is active per user")
    brands = one("SELECT COUNT(*) FROM domain_profiles")
    check("every brand has a label", one("SELECT COUNT(*) FROM domain_profiles WHERE label = ''"), 0)
    print(f"  [INFO] {brands} brands")
    dupes = one(
        "SELECT COUNT(*) FROM (SELECT user_id, domain, COUNT(*) c FROM domain_profiles "
        "WHERE is_active = 1 GROUP BY user_id, domain HAVING c > 1)"
    )
    check("no user has two active brands in a domain", dupes, 0)
    missing = one(
        "SELECT COUNT(*) FROM (SELECT user_id, domain FROM domain_profiles "
        "GROUP BY user_id, domain HAVING SUM(is_active) = 0)"
    )
    check("every user+domain has an active brand", missing, 0)

    print("\n2. Backfill linked every row that had a brand to link to")
    # A row is linked if and only if its user actually had a brand in that
    # domain. The old schema let an account configure agents while skipping the
    # brand step, so NULL here is a faithful "no brand yet", not a lost row.
    for table in ("agent_profiles", "conversations"):
        total = one(f"SELECT COUNT(*) FROM {table}")
        missed = one(
            f"SELECT COUNT(*) FROM {table} t WHERE t.brand_profile_id IS NULL "
            "AND EXISTS (SELECT 1 FROM domain_profiles d "
            "WHERE d.user_id = t.user_id AND d.domain = t.domain)"
        )
        check(f"{table}: no row left unlinked despite having a brand", missed, 0)
        brandless = one(
            f"SELECT COUNT(*) FROM {table} t WHERE t.brand_profile_id IS NULL"
        )
        print(f"  [INFO] {table}: {total} rows, {brandless} belong to brand-less accounts")

    print("\n3. Memory scope rules")
    scoped = one("SELECT COUNT(*) FROM memories WHERE domain IS NOT NULL")
    scoped_linked = one(
        "SELECT COUNT(*) FROM memories WHERE domain IS NOT NULL AND brand_profile_id IS NOT NULL"
    )
    check(f"brand/agent memories linked ({scoped} of them)", scoped_linked, scoped)
    globals_ = one("SELECT COUNT(*) FROM memories WHERE domain IS NULL")
    globals_unlinked = one(
        "SELECT COUNT(*) FROM memories WHERE domain IS NULL AND brand_profile_id IS NULL"
    )
    check(
        f"global memories span every brand ({globals_} of them)", globals_unlinked, globals_
    )

    print("\n4. No dangling brand references")
    for table in ("agent_profiles", "conversations", "memories"):
        dangling = one(
            f"SELECT COUNT(*) FROM {table} t WHERE t.brand_profile_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM domain_profiles d WHERE d.id = t.brand_profile_id)"
        )
        check(f"{table}: no orphan brand_profile_id", dangling, 0)

    print("\n5. The old single-brand constraints are gone")
    sql = {
        r["name"]: r["sql"]
        for r in con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name IN ('domain_profiles','agent_profiles')"
        )
    }
    check(
        "domain_profiles no longer UNIQUE(user_id, domain)",
        "uq_domain_profiles_user_domain" in (sql.get("domain_profiles") or ""),
        False,
    )
    check(
        "agent_profiles no longer UNIQUE(user_id, agent_key)",
        "uq_agent_profiles_user_agent" in (sql.get("agent_profiles") or ""),
        False,
    )
    check(
        "agent_profiles now UNIQUE(user_id, brand_profile_id, agent_key)",
        "uq_agent_profiles_user_brand_agent" in (sql.get("agent_profiles") or ""),
        True,
    )

    print("\n6. A second brand is now actually insertable")
    row = con.execute(
        "SELECT user_id, domain FROM domain_profiles LIMIT 1"
    ).fetchone()
    try:
        con.execute(
            "INSERT INTO domain_profiles (id, user_id, domain, label, is_active, "
            "profile_data, is_configured, revision, created_at, updated_at) "
            "VALUES ('ffffffffffffffffffffffffffffffff', ?, ?, 'Second brand', 0, "
            "'{}', 0, 1, datetime('now'), datetime('now'))",
            (row["user_id"], row["domain"]),
        )
        check("insert a 2nd brand for the same user+domain", True, True)
        con.rollback()
    except sqlite3.IntegrityError as exc:
        check(f"insert a 2nd brand (failed: {exc})", False, True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
