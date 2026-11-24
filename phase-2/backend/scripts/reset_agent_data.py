#!/usr/bin/env python3
"""Clear one account's agent-level data so every agent needs setup again.

Scoped to a single account on purpose. This database also holds ~25 throwaway
`eval+*` / `live+*` accounts that share the same brand name, and a brand-wide
delete would take those with it.

What goes, by default:
  * agent_profiles      -> all five agents return to "Not configured"
  * agent-scoped memories -> no learned preference survives the reset
  * conversations + messages -> no stale output in the sidebar

What stays, by default:
  * the user, their login, and their global profile
  * the brand (domain) profile, so setup step 1 stays answered

Pass --brand to clear the brand profile too, for a full two-step walkthrough.

    python scripts/reset_agent_data.py demo@example.com --dry-run
    python scripts/reset_agent_data.py demo@example.com --yes
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "marketing_agent.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="account to reset, e.g. demo@example.com")
    parser.add_argument("--brand", action="store_true",
                        help="also clear the brand/domain profile")
    parser.add_argument("--keep-conversations", action="store_true",
                        help="leave chat history in place")
    parser.add_argument("--keep-memories", action="store_true",
                        help="leave learned memories in place")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be deleted, change nothing")
    parser.add_argument("--yes", action="store_true",
                        help="required to actually delete")
    args = parser.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    row = con.execute(
        "SELECT id, email, name FROM users WHERE lower(email) = ?",
        (args.email.strip().lower(),),
    ).fetchone()
    if row is None:
        print(f"No account with e-mail {args.email!r}.")
        return 1

    uid, email, name = row["id"], row["email"], row["name"]
    print(f"Account: {email}  ({name})")
    print(f"user_id: {uid}\n")

    # Build the plan as (label, count-sql, delete-sql) so the dry run and the
    # real run can never describe different things.
    plan: list[tuple[str, str, str]] = [
        (
            "agent_profiles",
            "SELECT COUNT(*) FROM agent_profiles WHERE user_id = ?",
            "DELETE FROM agent_profiles WHERE user_id = ?",
        )
    ]
    if not args.keep_memories:
        plan.append((
            "memories (agent-scoped)",
            "SELECT COUNT(*) FROM memories WHERE user_id = ? AND agent_key IS NOT NULL",
            "DELETE FROM memories WHERE user_id = ? AND agent_key IS NOT NULL",
        ))
    if not args.keep_conversations:
        plan.append((
            "messages",
            "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)",
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)",
        ))
        plan.append((
            "feedback",
            "SELECT COUNT(*) FROM feedback WHERE user_id = ?",
            "DELETE FROM feedback WHERE user_id = ?",
        ))
        plan.append((
            "conversations",
            "SELECT COUNT(*) FROM conversations WHERE user_id = ?",
            "DELETE FROM conversations WHERE user_id = ?",
        ))
    if args.brand:
        plan.append((
            "domain_profiles (brand)",
            "SELECT COUNT(*) FROM domain_profiles WHERE user_id = ?",
            "DELETE FROM domain_profiles WHERE user_id = ?",
        ))

    print("Will delete:")
    total = 0
    for label, count_sql, _ in plan:
        n = con.execute(count_sql, (uid,)).fetchone()[0]
        total += n
        print(f"  {label:26} {n}")

    kept = ["users", "global_profiles"]
    if not args.brand:
        kept.append("domain_profiles (brand stays answered)")
    if args.keep_memories:
        kept.append("memories")
    if args.keep_conversations:
        kept.append("conversations + messages")
    print("\nWill keep: " + ", ".join(kept))

    if args.dry_run:
        print(f"\nDry run — nothing changed. {total} rows would go.")
        return 0
    if not args.yes:
        print("\nRefusing to delete without --yes.")
        return 2

    for _, _, delete_sql in plan:
        con.execute(delete_sql, (uid,))
    con.commit()
    print(f"\nDeleted {total} rows.")

    print("\nState now:")
    for table in ("agent_profiles", "domain_profiles", "global_profiles",
                  "conversations", "messages", "memories"):
        if table == "messages":
            n = con.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE user_id = ?)", (uid,)
            ).fetchone()[0]
        else:
            n = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)
            ).fetchone()[0]
        print(f"  {table:20} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
