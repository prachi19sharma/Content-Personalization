#!/usr/bin/env python3
"""Assert caption output is paste-able: no scaffolding, spacing intact.

Measured defect. Asked for a LinkedIn caption, llama3.2:3b returned:

    Headline: Don't let your resume collect dust
    Body:
    We've all been there - staring at a blank page...

    Why this works:
    This caption uses a relatable scenario...

None of that can be pasted into a post box. The "Why this works" section was
actually requested by the agent's own instructions (now removed); the
"Headline:"/"Body:" labels never were, which is the familiar result that a small
model does not reliably honour a negative instruction.

The hard part is not stripping the scaffolding -- it is stripping it without
destroying the blank lines that make a caption readable. The first version of
the regex used ``\\s*`` after the label colon, which swallowed the newline and
welded the paragraphs into a wall of text. Several checks below exist purely to
pin that down.

No model calls.

    python scripts/check_paste_ready.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.catalog import get_agent_spec  # noqa: E402
from app.agents.paste_ready import make_paste_ready  # noqa: E402

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


MEASURED = (
    "Headline: Don't let your resume collect dust\n"
    "Body:\n"
    "We've all been there - staring at a blank page.\n"
    "\n"
    "Our expert guidance will help you craft a standout resume.\n"
    "\n"
    "Why this works:\n"
    "This caption uses a relatable scenario and positions us as the solution.\n"
)


def main() -> int:
    print("\n1. The exact output measured from llama3.2:3b")
    cleaned, removed = make_paste_ready(MEASURED)
    check("the 'Headline:' label is gone", "Headline:" in cleaned, False)
    check("the 'Body:' label is gone", "Body:" in cleaned, False)
    check("the explainer is gone", "Why this works" in cleaned, False)
    check("the hook survived", cleaned.startswith("Don't let your resume"), True)
    check("the body survived", "staring at a blank page" in cleaned, True)
    check("both removals were reported", sorted(removed), ["explanatory section", "field labels"])

    print("\n2. Spacing is preserved — this is the part that broke first")
    lines = cleaned.split("\n")
    check("hook is its own line", lines[0], "Don't let your resume collect dust")
    check("a blank line follows the hook", lines[1], "")
    check("paragraphs stay separated", "" in lines[2:], True)
    check("no wall of text", "\n\n" in cleaned, True)
    check("no triple newline left behind", "\n\n\n" in cleaned, False)

    print("\n3. Preamble and wrapping quotes")
    for raw, label in (
        ("Sure! Here is your caption:\n\nLaunch day is here.", "preamble"),
        ('"Launch day is here."', "wrapping quotes"),
        ("Here's a LinkedIn caption:\n\nLaunch day is here.", "here's preamble"),
    ):
        out, _ = make_paste_ready(raw)
        check(f"{label} stripped", out, "Launch day is here.")

    print("\n4. Real copy must NOT be damaged")
    keep = (
        "Your resume deserves better.\n"
        "\n"
        'One founder told us "I had no idea where to start" — and that is normal.\n'
        "\n"
        "Start today.\n"
        "\n"
        "#internships #careers #hiring"
    )
    out, removed = make_paste_ready(keep)
    check("nothing was removed", removed, [])
    check("an inline quotation survives", '"I had no idea where to start"' in out, True)
    check("hashtags survive", out.endswith("#internships #careers #hiring"), True)
    check("blank lines survive", out.count("\n\n"), 3)

    # A sentence that merely mentions a label word must be left alone.
    out, _ = make_paste_ready("The hook: it actually works.")
    check(
        "a mid-sentence label word is untouched",
        out,
        "The hook: it actually works.",
    )

    print("\n5. The agent is wired to use it")
    spec = get_agent_spec("marketing.social-copy")
    check("social-copy declares paste_ready", bool(spec.options.get("paste_ready")), True)
    lowered = spec.instructions.lower()
    check("the prompt no longer asks for 'Why this works'", "add at most two lines under" in lowered, False)
    for phrase in ('"headline:"', "why this works", "preamble", "quotation marks"):
        check(f"the prompt forbids {phrase}", phrase in lowered, True)
    check("the prompt demands blank lines", "blank line" in lowered, True)
    check("the prompt requires hashtags when enabled", "must actually include them" in lowered, True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
