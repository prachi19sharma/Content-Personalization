#!/usr/bin/env python3
"""Assert a platform named in the request sets the canvas, beating the profile.

Measured defect this guards: asking the post-image agent for "An Instagram
graphic announcing our new pricing" rendered at 1200x627 -- the LinkedIn size
from the profile -- because `ImageAgent._size` only ever read the profile. The
agent's own suggestion chips include that exact phrasing, so the app shipped a
prompt it then answered at the wrong dimensions.

Also guards the opposite direction, which matters more: an incidental word must
NOT hijack the canvas. "A story about our launch" is prose, not a request for a
1080x1920 story.

No model calls, no network, no database.

    python scripts/check_canvas_override.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.catalog import get_agent_spec  # noqa: E402
from app.agents.runtime import ImageAgent  # noqa: E402

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


def agent(key: str) -> ImageAgent:
    return ImageAgent(get_agent_spec(key))


def main() -> int:
    post = agent("marketing.post-image")
    ad = agent("marketing.ad-creative")

    # The profile says LinkedIn throughout, so every override below has to
    # fight an actively-set default rather than an empty one.
    li = {"platform": "LinkedIn"}

    print("\n1. Post image: the request wins over the profile")
    cases = [
        ("An Instagram graphic announcing our new pricing", (1080, 1080)),
        ("instagram story for the launch", (1080, 1920)),
        ("Make an IG story about our webinar", (1080, 1920)),
        ("a square instagram post", (1080, 1080)),
        ("Facebook image for the sale", (1200, 630)),
        ("post this on Twitter", (1200, 675)),
        ("A LinkedIn post image about AI automation", (1200, 627)),
    ]
    for request, want in cases:
        w, h, source = post._size(li, request)
        check(f"{request[:46]!r}", (w, h), want)
        if want != (1200, 627):  # LinkedIn matches the profile anyway
            check(f"  ...source is the request", source.startswith("request:"), True)

    print("\n2. Post image: the profile is used when the request names nothing")
    for platform, want in [
        ("LinkedIn", (1200, 627)),
        ("Instagram (square)", (1080, 1080)),
        ("Instagram (story)", (1080, 1920)),
        ("X / Twitter", (1200, 675)),
        ("Facebook", (1200, 630)),
    ]:
        w, h, source = post._size({"platform": platform}, "announce our new pricing")
        check(f"profile {platform!r}", (w, h), want)
        check("  ...source is the profile", source, f"profile:{platform}")

    print("\n3. Post image: incidental words must NOT set the canvas")
    for request in [
        "A story about our launch week",
        "Tell the story of our founding",
        "a square deal for customers",
        "write about our instagrammable office",  # no word-boundary match
    ]:
        w, h, source = post._size(li, request)
        check(f"{request[:40]!r} stays on profile", (w, h), (1200, 627))
        check("  ...source is the profile", source, "profile:LinkedIn")

    print("\n4. Ad creative: shape words are honoured")
    land = {"size": "Landscape 1200x628"}
    for request, want in [
        ("a square ad for the free trial", (1080, 1080)),
        ("leaderboard banner for the trial", (728, 90)),
        ("vertical story ad", (1080, 1920)),
        ("landscape creative", (1200, 628)),
        ("an instagram story ad", (1080, 1920)),
    ]:
        w, h, _ = ad._size(land, request)
        check(f"{request[:40]!r}", (w, h), want)

    print("\n5. Fallbacks")
    w, h, source = post._size({}, "")
    check("empty profile + empty request -> default", (w, h), (1200, 627))
    check("  ...source is the default", source, "default")
    w, h, source = post._size({"style": "Minimal"}, "")
    check("profile without a platform -> default", (w, h), (1200, 627))

    print("\n6. Every declared alias points at a real size")
    for key in ("marketing.post-image", "marketing.ad-creative"):
        spec = get_agent_spec(key)
        sizes = spec.options.get("sizes", {})
        aliases = spec.options.get("size_aliases", ())
        bad = [(p, k) for p, k in aliases if k not in sizes]
        check(f"{key} aliases resolve", bad, [])
        field_key = spec.options.get("size_field")
        declared = {f.key for f in spec.profile_fields}
        check(f"{key} size_field is a real field", field_key in declared, True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
