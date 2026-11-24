#!/usr/bin/env python3
"""Inspect one brand's data before clearing it.

Read-only. Prints which account owns the brand and exactly what rows hang off
it, so a delete can be scoped to that user rather than the whole database
(this DB also holds ~30 accounts left over from eval and verify runs).

    python scripts/inspect_brand.py "ACME Cloud"
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "marketing_agent.db"


def brand_name_of(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("brand_name")
    return str(value) if value else None


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "ACME Cloud").strip().lower()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    matches: list[tuple[str, str, str, str]] = []
    for row in con.execute(
        "SELECT dp.user_id, dp.domain, dp.profile_data, u.email, u.name "
        "FROM domain_profiles dp JOIN users u ON u.id = dp.user_id"
    ):
        name = brand_name_of(row["profile_data"])
        if name and needle in name.lower():
            matches.append((row["user_id"], row["email"], row["name"], name))

    if not matches:
        print(f"No account has a brand matching {needle!r}.")
        print("\nBrands present:")
        seen: dict[str, int] = {}
        for row in con.execute("SELECT profile_data FROM domain_profiles"):
            name = brand_name_of(row["profile_data"]) or "(unnamed)"
            seen[name] = seen.get(name, 0) + 1
        for name, count in sorted(seen.items(), key=lambda kv: -kv[1]):
            print(f"  {count:3}x  {name}")
        return 1

    print(f"Accounts whose brand matches {needle!r}: {len(matches)}\n")
    for user_id, email, name, brand in matches:
        print(f"  {email}  ({name})   brand={brand!r}")
        print(f"    user_id = {user_id}")

        counts = {
            "agent_profiles": "SELECT COUNT(*) FROM agent_profiles WHERE user_id = ?",
            "domain_profiles": "SELECT COUNT(*) FROM domain_profiles WHERE user_id = ?",
            "global_profiles": "SELECT COUNT(*) FROM global_profiles WHERE user_id = ?",
            "conversations": "SELECT COUNT(*) FROM conversations WHERE user_id = ?",
            "memories": "SELECT COUNT(*) FROM memories WHERE user_id = ?",
            "feedback": "SELECT COUNT(*) FROM feedback WHERE user_id = ?",
        }
        for label, sql in counts.items():
            print(f"      {label:18} {con.execute(sql, (user_id,)).fetchone()[0]}")

        messages = con.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)",
            (user_id,),
        ).fetchone()[0]
        print(f"      {'messages':18} {messages}")

        print("      agent profiles:")
        for row in con.execute(
            "SELECT agent_key, is_configured, interaction_count FROM agent_profiles "
            "WHERE user_id = ? ORDER BY agent_key",
            (user_id,),
        ):
            print(
                f"        {row['agent_key']:30} configured={row['is_configured']} "
                f"interactions={row['interaction_count']}"
            )

        print("      memories by scope:")
        for row in con.execute(
            "SELECT COALESCE(agent_key, domain, 'global') AS scope, COUNT(*) AS n "
            "FROM memories WHERE user_id = ? GROUP BY scope ORDER BY n DESC",
            (user_id,),
        ):
            print(f"        {row['scope']:30} {row['n']}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
