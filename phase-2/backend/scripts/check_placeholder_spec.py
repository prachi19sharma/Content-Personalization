#!/usr/bin/env python3
"""Assert an echoed prompt hint never reaches a rendered graphic.

Measured defect this guards. The post-image prompt shows the model a JSON
skeleton with bracketed hints:

    "headline": "<max 8 words, the single idea, title case off>"

Asked for an Instagram graphic, llama3.2:3b returned that hint *verbatim*. It is
a non-empty string, so the "did the model answer?" check passed, the renderer
printed it onto the card, and `incomplete_reason` stayed None -- the app shipped
a graphic reading "<max 8 words, the single idea, title case off>" and reported
success.

Two things are asserted here:
  * hints are detected and blanked, and the turn is marked degraded;
  * real copy is never mistaken for a hint, which matters more -- a false
    positive would throw away a perfectly good headline.

No model calls, no network, no database.

    python scripts/check_placeholder_spec.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.definitions import marketing  # noqa: E402
from app.media import ImageSpec, is_placeholder  # noqa: E402

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
    print("\n1. The hints in the real prompt are all detected")
    # Pulled from the live AgentSpec rather than retyped, so editing the prompt
    # cannot quietly leave this check guarding text that no longer exists.
    instructions = marketing.POST_IMAGE.instructions
    hints = [
        line.split('":', 1)[1].strip().strip(",").strip('"')
        for line in instructions.splitlines()
        if '": "<' in line
    ]
    check("found hints in the prompt to test", len(hints) >= 4, True)
    for hint in hints:
        check(f"{hint[:50]!r}", is_placeholder(hint), True)

    print("\n2. Real copy is NOT mistaken for a hint")
    for real in (
        "Simplify Dev Team Cost Management",
        "Streamline cloud spend with our AI-driven cost optimization",
        "Acme Cloud",
        "Learn More",
        "Save 30% on idle cloud spend",
        "A dashboard showing idle cloud resources for developer teams",
        "Up to 8 words of genuine marketing copy",
        "Cut costs. Keep shipping.",
    ):
        check(f"{real[:50]!r}", is_placeholder(real), False)

    print("\n3. Empty is not a placeholder (it is just empty)")
    for blank in ("", "   ", None):
        check(f"{blank!r}", is_placeholder(blank), False)

    print("\n4. sanitized() blanks hints and records which were blanked")
    spec = ImageSpec(
        headline="<max 8 words, the single idea, title case off>",
        subline="Streamline cloud spend across every team",
        badge="<max 3 words, optional eyebrow/tag, may be empty>",
        cta="Learn More",
        alt_text="<one sentence describing the image for accessibility>",
    ).sanitized()
    check("headline blanked", spec.headline, "")
    check("real subline kept", spec.subline, "Streamline cloud spend across every team")
    check("badge blanked", spec.badge, "")
    check("real cta kept", spec.cta, "Learn More")
    check("alt_text blanked", spec.alt_text, "")
    check(
        "recorded exactly the blanked fields",
        sorted(spec.placeholder_fields),
        ["alt_text", "badge", "headline"],
    )

    print("\n5. A clean spec records nothing")
    clean = ImageSpec(
        headline="Simplify Dev Team Cost Management",
        subline="Cut idle spend without slowing delivery",
        cta="Learn More",
        alt_text="A brand-coloured card about cloud cost optimization",
    ).sanitized()
    check("no fields flagged", clean.placeholder_fields, [])
    check("headline survived", clean.headline, "Simplify Dev Team Cost Management")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
