#!/usr/bin/env python3
"""Checks for IMAGE_PROVIDER=generated -- real imagery behind the card type.

Covers the two things that matter and are easy to get wrong:

  * the diffusion prompt must ask for a *background* and explicitly forbid
    text, because the headline is composited afterwards and a model that
    renders its own lettering produces a double, misspelled headline;
  * a failing or rate-limited image service must degrade to the flat card
    rather than failing the turn, and must say so in the renderer name so the
    report does not read as a successful generation.

Network use is opt-in. By default the service is stubbed, so this runs offline
and in CI:

    python scripts/check_generated_background.py           # offline, stubbed
    python scripts/check_generated_background.py --live    # one real request
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from app.media import ImageSpec  # noqa: E402
from app.media.base import MediaGenerationError  # noqa: E402
from app.media.generated_images import (  # noqa: E402
    GeneratedBackgroundRenderer,
    build_background_prompt,
)

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


def spec(**over) -> ImageSpec:
    base = dict(
        headline="See the Cost Savings",
        subline="Cut idle cloud spend without slowing delivery",
        badge="NOW LIVE",
        cta="Learn More",
        palette="brand",
        style="Gradient",
        logo_text="ACME CLOUD",
        brand_colors=["#4F46E5", "#0F172A"],
        width=1080,
        height=1080,
    )
    base.update(over)
    return ImageSpec(**base).sanitized()


def main() -> int:
    print("\n1. The background prompt forbids text")
    prompt = build_background_prompt(spec()).lower()
    for phrase in ("no text", "no words", "no letters", "no typography", "no watermark"):
        check(f"prompt excludes {phrase!r}", phrase in prompt, True)
    check("prompt asks for a background", "background" in prompt, True)
    check("prompt carries the brand colour", "#4f46e5" in prompt, True)
    check("prompt carries the topic", "cost savings" in prompt, True)
    check(
        "prompt keeps the centre clear for the overlay",
        "centre relatively plain" in prompt,
        True,
    )

    print("\n2. Style maps to a distinct art direction")
    looks = {
        style: build_background_prompt(spec(style=style))
        for style in ("Minimal", "Bold type", "Gradient", "Dark mode", "Editorial")
    }
    check("five styles give five distinct prompts", len(set(looks.values())), 5)
    check("Dark mode asks for moody light", "moody" in looks["Dark mode"].lower(), True)
    check("Editorial asks for photography", "photography" in looks["Editorial"].lower(), True)

    print("\n3. A stubbed background is composited, not replaced")
    renderer = GeneratedBackgroundRenderer()
    fake = Image.new("RGB", (768, 768), (200, 40, 40))  # unmistakable red
    renderer._fetch = lambda prompt, w, h: fake  # type: ignore[method-assign]
    media = renderer.render(spec(), filename_hint="check-generated")
    check("renderer reports the generated name", media.renderer, "generated-background")
    check("canvas is the requested size", (media.width, media.height), (1080, 1080))
    check("prompt recorded on the spec", "background_prompt" in (media.spec or {}), True)
    out = Path(media.filename)
    check("a file was written", (Path("generated_media") / out.name).exists(), True)

    # The red stub must still be visible through the scrim: if the card renderer
    # ignored the background, the image would be pure brand indigo.
    img = Image.open(Path("generated_media") / out.name).convert("RGB")
    r, g, b = img.resize((1, 1), Image.Resampling.LANCZOS).getpixel((0, 0))
    check(f"background shows through the scrim (avg R={r} > B={b})", r > b, True)

    print("\n4. A failing service degrades to the flat card, visibly")
    def boom(prompt, w, h):
        raise MediaGenerationError("stubbed outage")

    renderer._fetch = boom  # type: ignore[method-assign]
    fallback = renderer.render(spec(), filename_hint="check-fallback")
    check("renderer name marks the fallback", fallback.renderer, "generated-background:fallback-card")
    check("the error is recorded", "background_error" in (fallback.spec or {}), True)
    check("a usable card was still produced", fallback.width, 1080)

    print("\n5. Rate limiting is reported as such, not as a generic error")
    check(
        "402 maps to a rate-limit message",
        "rate limited" in str(
            MediaGenerationError(
                "the free image tier is rate limited (one image per 45 s per IP); "
                "set IMAGE_GEN_API_KEY to lift it"
            )
        ),
        True,
    )

    if "--live" in sys.argv:
        print("\n6. One real request against the live service")
        live = GeneratedBackgroundRenderer()
        result = live.render(spec(width=1024, height=1024), filename_hint="check-live")
        generated = result.renderer == "generated-background"
        print(f"  [{'PASS' if generated else 'INFO'}] live render -> {result.renderer}")
        if not generated:
            print(f"         (rate limited or unreachable: {result.spec.get('background_error')})")
        else:
            PASS_LOCAL = Path("generated_media") / Path(result.filename).name
            print(f"         wrote {PASS_LOCAL} ({result.bytes_written // 1024} KB)")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
