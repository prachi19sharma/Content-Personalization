"""Real generated imagery behind the card typography.

Selected with ``IMAGE_PROVIDER=generated``.

The local card renderer draws text on a flat gradient -- no pixels are ever
generated, which is why every output looks like a typographic poster rather than
a picture. This renderer asks a text-to-image service for an actual background
and then hands it to the card renderer, so the artwork comes from a diffusion
model while the words stay Pillow-drawn.

The split is deliberate. Diffusion models garble lettering, and a marketing
graphic with a misspelled headline is unusable however good the art is. So the
image prompt explicitly asks for **no text**, and the headline, subline, badge
and CTA are composited on top at full crispness.

Backend: Pollinations (https://pollinations.ai), which needs no API key and no
account. ``IMAGE_GEN_URL`` can point at anything that returns image bytes for a
URL-encoded prompt, so a self-hosted Stable Diffusion endpoint drops in without
code changes.
"""

from __future__ import annotations

import io
import urllib.parse
from typing import Any

import httpx
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger
from app.media.base import BaseImageRenderer, ImageSpec, MediaGenerationError, RenderedMedia
from app.media.card_renderer import LocalCardRenderer

logger = get_logger(__name__)

#: Asking for the canvas size directly is wasteful -- the service caps the long
#: edge anyway and the card renderer cover-fits whatever it gets. Request a
#: generous square-ish source and let the crop decide the final framing.
_MAX_EDGE = 1024


def _subject(spec: ImageSpec) -> str:
    """What the picture should be *of*, inferred from the copy.

    The headline is the only reliable description of the topic available, but it
    is marketing phrasing ("See the Cost Savings"), not an art direction. It is
    passed as subject matter rather than as text to render.
    """
    bits = [spec.headline]
    if spec.subline:
        bits.append(spec.subline)
    return " ".join(part for part in bits if part)[:300]


def build_background_prompt(spec: ImageSpec) -> str:
    """Compose the diffusion prompt for the background only."""
    style_map = {
        "minimal": "clean minimal composition, lots of negative space, soft light",
        "bold type": "bold graphic composition, strong shapes, high contrast",
        "gradient": "smooth colour gradients, soft abstract forms",
        "dark mode": "dark moody lighting, deep shadows, subtle highlights",
        "editorial": "editorial photography, natural light, shallow depth of field",
    }
    look = style_map.get((spec.style or "").strip().lower(), "clean modern composition")

    parts = [
        f"Professional marketing background image about: {_subject(spec)}.",
        look,
    ]
    if spec.brand_colors:
        parts.append(f"Colour palette dominated by {', '.join(spec.brand_colors[:2])}")
    parts.append(
        "abstract and uncluttered, leaving the centre relatively plain so a "
        "headline can be overlaid"
    )
    # Negative guidance. Pollinations has no separate negative-prompt field, so
    # the exclusions live in the prompt itself.
    parts.append(
        "absolutely no text, no words, no letters, no numbers, no typography, "
        "no logos, no watermark, no signature, no UI mockup, no charts"
    )
    return ", ".join(parts)


class GeneratedBackgroundRenderer(BaseImageRenderer):
    """Diffusion-generated background + locally drawn typography."""

    name = "generated-background"

    def __init__(self) -> None:
        self._cards = LocalCardRenderer()

    def _fetch_huggingface(self, prompt: str, width: int, height: int) -> Image.Image:
        """Inference Providers router: POST JSON, get image bytes.

        This is the practical route to models like Qwen-Image, which need
        ~16 GB of VRAM at FP16 and cannot run on a machine with no GPU.
        """
        if not settings.IMAGE_GEN_API_KEY:
            raise MediaGenerationError(
                "IMAGE_GEN_BACKEND=huggingface needs IMAGE_GEN_API_KEY "
                "(a free token from huggingface.co/settings/tokens)"
            )
        url = f"{settings.IMAGE_GEN_URL.rstrip('/')}/{settings.IMAGE_GEN_MODEL}"
        payload = {
            "inputs": prompt,
            "parameters": {"width": width, "height": height},
        }
        try:
            with httpx.Client(
                timeout=settings.IMAGE_GEN_TIMEOUT, follow_redirects=True
            ) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.IMAGE_GEN_API_KEY}",
                        "Accept": "image/png",
                    },
                )
        except httpx.HTTPError as exc:
            raise MediaGenerationError(f"Image service unreachable: {exc}") from exc

        if response.status_code == 503:
            raise MediaGenerationError(
                "the model is loading on the provider; retry in a moment"
            )
        if response.status_code >= 400:
            raise MediaGenerationError(
                f"Image service returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            return Image.open(io.BytesIO(response.content))
        except Exception as exc:
            raise MediaGenerationError(f"Image service returned undecodable data: {exc}") from exc

    def _fetch(self, prompt: str, width: int, height: int) -> Image.Image:
        # Keep the requested aspect ratio but bound the long edge.
        ratio = width / max(height, 1)
        if ratio >= 1:
            req_w = min(_MAX_EDGE, max(width, 512))
            req_h = max(256, round(req_w / ratio))
        else:
            req_h = min(_MAX_EDGE, max(height, 512))
            req_w = max(256, round(req_h * ratio))

        if settings.IMAGE_GEN_BACKEND == "huggingface":
            return self._fetch_huggingface(prompt, req_w, req_h)

        base = settings.IMAGE_GEN_URL.rstrip("/")
        url = f"{base}/{urllib.parse.quote(prompt, safe='')}"
        params = {
            "width": req_w,
            "height": req_h,
            "nologo": "true",
            "model": settings.IMAGE_GEN_MODEL,
        }
        if settings.IMAGE_GEN_SEED is not None:
            params["seed"] = settings.IMAGE_GEN_SEED

        headers = {}
        if settings.IMAGE_GEN_API_KEY:
            headers["Authorization"] = f"Bearer {settings.IMAGE_GEN_API_KEY}"

        try:
            with httpx.Client(
                timeout=settings.IMAGE_GEN_TIMEOUT, follow_redirects=True
            ) as client:
                response = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise MediaGenerationError(f"Image service unreachable: {exc}") from exc

        if response.status_code == 402:
            # Anonymous tier throttle. Distinguished from a real failure so the
            # message tells the user what to do instead of "service error".
            raise MediaGenerationError(
                "the free image tier is rate limited (one image per 45 s per IP); "
                "set IMAGE_GEN_API_KEY to lift it"
            )

        if response.status_code >= 400:
            raise MediaGenerationError(
                f"Image service returned HTTP {response.status_code}: {response.text[:200]}"
            )
        if not response.content:
            raise MediaGenerationError("Image service returned an empty body.")
        # Guard against an HTML error page arriving with a 200.
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type:
            raise MediaGenerationError(
                f"Image service returned {content_type or 'an unknown type'}, not an image."
            )

        try:
            return Image.open(io.BytesIO(response.content))
        except Exception as exc:  # Pillow raises a variety of types here
            raise MediaGenerationError(f"Image service returned undecodable data: {exc}") from exc

    def render(self, spec: ImageSpec, *, filename_hint: str = "image") -> RenderedMedia:
        spec = spec.sanitized()
        prompt = build_background_prompt(spec)

        try:
            background = self._fetch(prompt, spec.width, spec.height)
        except MediaGenerationError as exc:
            # A card with no picture is still a usable deliverable; no card at
            # all is not. Fall back rather than failing the turn, and say so in
            # the renderer name so it is visible in the report instead of
            # looking like a successful generation.
            logger.warning("%s: %s; falling back to the flat card", self.name, exc)
            media = self._cards.render(spec, filename_hint=filename_hint)
            media.renderer = f"{self.name}:fallback-card"
            media.spec = {**(media.spec or {}), "background_error": str(exc)}
            return media

        logger.info("%s: generated a %s background", self.name, background.size)
        media = self._cards.render(spec, filename_hint=filename_hint, background=background)
        media.renderer = self.name
        media.spec = {
            **(media.spec or {}),
            "background_prompt": prompt,
            "background_model": settings.IMAGE_GEN_MODEL,
            "background_source": background.size,
        }
        return media

    def health(self) -> dict[str, Any]:
        return {
            "renderer": self.name,
            "endpoint": settings.IMAGE_GEN_URL,
            "model": settings.IMAGE_GEN_MODEL,
            "api_key_required": False,
            "ok": True,
        }
