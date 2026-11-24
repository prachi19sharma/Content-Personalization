#!/usr/bin/env python3
"""Render one identical spec under every style, to see what the style actually does.

The model only ever returns a palette *name*; the colours come from
`build_theme` in app/media/card_renderer.py, which can override that name based
on the agent profile's "Visual style". So "every image is white" is a renderer
question, not a model question -- this makes that visible.

    python scripts/palette_preview.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.media import ImageSpec  # noqa: E402
from app.media.card_renderer import build_theme  # noqa: E402

STYLES = ("Minimal", "Bold type", "Gradient", "Dark mode", "Editorial", "")
BRAND = ["#4F46E5", "#7C3AED"]  # the Acme Cloud indigo/violet


def swatch(rgb) -> str:
    return "#%02X%02X%02X" % rgb


def main() -> int:
    print(f"\nbrand colours from the profile: {', '.join(BRAND)}")
    print("\nmodel says palette='brand' every time. What the renderer actually does:\n")
    print(f"  {'style':12} {'-> palette':12} {'base top':10} {'base bottom':12} {'text':10} accent")
    print("  " + "-" * 72)

    for style in STYLES:
        spec = ImageSpec(
            headline="See the Cost Savings",
            subline="Cut idle cloud spend without slowing delivery",
            cta="Learn More",
            palette="brand",
            style=style,
            brand_colors=list(BRAND),
        ).sanitized()
        theme = build_theme(spec)

        # Re-derive which branch build_theme took, for the report.
        low = style.lower()
        if "dark" in low or "moody" in low:
            resolved = "dark"
        elif "minimal" in low:
            resolved = "light"
        elif "gradient" in low or "retro" in low:
            resolved = "gradient"
        else:
            resolved = "brand"

        flag = "  <-- near-white" if resolved == "light" else ""
        print(
            f"  {style or '(unset)':12} {resolved:12} {swatch(theme.top):10} "
            f"{swatch(theme.bottom):12} {swatch(theme.text):10} {swatch(theme.accent)}{flag}"
        )

    print(
        "\nstyle='Minimal' in the agent profile forces palette 'light'. That base used to be\n"
        "#F8FAFC -> #E2E8F0 (neutral slate grey, no brand in it at all), which is why every\n"
        "Minimal card looked generic white. It is now blended from the brand primary, so a\n"
        "light card still reads as that brand. Switching generator model changes none of\n"
        "this -- the colours never come from the model, only the palette *name* does."
    )

    out = Path(__file__).resolve().parent.parent / "generated_media"
    if "--render" in sys.argv:
        from app.media.card_renderer import LocalCardRenderer

        renderer = LocalCardRenderer()
        print(f"\nRendering one card per style into {out}/ ...")
        for style in STYLES:
            spec = ImageSpec(
                headline="See the Cost Savings",
                subline="Cut idle cloud spend without slowing delivery",
                badge="NOW LIVE",
                cta="Learn More",
                palette="brand",
                style=style,
                logo_text="ACME CLOUD",
                brand_colors=list(BRAND),
                width=1080,
                height=1080,
            ).sanitized()
            media = renderer.render(
                spec, filename_hint=f"preview-{(style or 'unset').lower().replace(' ', '-')}"
            )
            print(f"  {style or '(unset)':12} -> {media.filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
