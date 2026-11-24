#!/usr/bin/env python3
"""Summarise a harness report as accuracy: overall, per agent, per category.

Reads the stored report rather than re-running anything, so the numbers
describe exactly the run named on the command line.

    python scripts/marketing_eval/accuracy.py                 # newest report
    python scripts/marketing_eval/accuracy.py <label-or-path>
"""

from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

REPORTS = Path(__file__).resolve().parent / "reports"


def find(arg: str | None) -> Path:
    if arg:
        direct = Path(arg)
        if direct.is_file():
            return direct
        hits = sorted(REPORTS.glob(f"*{arg}*.json"))
        hits = [h for h in hits if ".scores" not in h.name]
        if not hits:
            raise SystemExit(f"no report matching {arg!r}")
        return hits[-1]
    hits = sorted(
        (p for p in REPORTS.glob("*.json") if ".scores" not in p.name),
        key=lambda p: p.stat().st_mtime,
    )
    if not hits:
        raise SystemExit("no reports found")
    return hits[-1]


def bar(passed: int, total: int, width: int = 24) -> str:
    if total == 0:
        return " " * width
    filled = round(width * passed / total)
    return "#" * filled + "." * (width - filled)


def main() -> int:
    path = find(sys.argv[1] if len(sys.argv) > 1 else None)
    data = json.loads(path.read_text())
    cases = data.get("cases", [])
    totals = data.get("totals") or data.get("summary") or {}
    config = data.get("config") or data.get("run") or {}

    print(f"\nreport : {path.name}")
    provider = config.get("provider") or data.get("provider") or "?"
    model = config.get("model") or data.get("model") or "?"
    print(f"model  : {provider} / {model}")
    print(f"elapsed: {totals.get('elapsed_seconds', data.get('elapsed_seconds', '?'))}s")

    # ---------------------------------------------------------------- overall
    passed = failed = 0
    skipped = errored = 0
    per_agent: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    failures: list[tuple[str, str, str]] = []

    for case in cases:
        if case.get("skipped"):
            skipped += 1
            continue
        if case.get("error"):
            errored += 1
        agent = (case.get("agent") or "?").replace("marketing.", "")
        cat = case.get("category") or "?"
        for assertion in case.get("assertions") or []:
            ok = bool(assertion.get("passed"))
            passed += ok
            failed += not ok
            per_agent[agent][0] += ok
            per_agent[agent][1] += 1
            per_cat[cat][0] += ok
            per_cat[cat][1] += 1
            if not ok:
                failures.append(
                    (case.get("id", "?"), assertion.get("label", "?"), str(assertion.get("detail", "")))
                )

    total = passed + failed
    rate = (100.0 * passed / total) if total else 0.0

    print("\n" + "=" * 62)
    print(f"ACCURACY   {passed}/{total} assertions   {rate:.1f}%")
    print("=" * 62)
    print(f"  cases run      : {len(cases) - skipped} of {len(cases)}  ({skipped} skipped)")
    print(f"  errors         : {errored}")
    print(f"  degraded specs : {totals.get('degraded_image_specs', '?')}")

    print("\nBy agent")
    for agent, (ok, n) in sorted(per_agent.items(), key=lambda kv: -kv[1][1]):
        pct = 100.0 * ok / n if n else 0
        print(f"  {agent:20} {ok:3}/{n:<3} {pct:5.1f}%  {bar(ok, n)}")

    print("\nBy category")
    for cat, (ok, n) in sorted(per_cat.items(), key=lambda kv: -kv[1][1]):
        pct = 100.0 * ok / n if n else 0
        print(f"  {cat:20} {ok:3}/{n:<3} {pct:5.1f}%  {bar(ok, n)}")

    if failures:
        print(f"\nFailed assertions ({len(failures)})")
        for case_id, label, detail in failures:
            tail = f" -> {detail[:60]}" if detail else ""
            print(f"  {case_id:34} {label}{tail}")
    else:
        print("\nNo failed assertions.")

    print(
        "\nNote: this is the DETERMINISTIC half -- routing, scope handoff, output kind,\n"
        "media geometry, hashtag and length bounds, whether the profile and memories\n"
        "reached the prompt, and no-fabrication checks. It does not measure whether the\n"
        "copy is any good; that needs the judge (scripts/marketing_eval/judge.py), and\n"
        "judge scores carry a measured noise floor of ~0.5 on a five-point scale."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
