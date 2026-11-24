"""Turn an attached image into text, so a text-only model can use it.

Why this exists. Making the *writing* model multimodal is the obvious move and
the wrong one: the small open vision models are image describers, not
copywriters. Pinning the caption agent to ``llava:7b`` so it could see a
reference image produced flat prose wrapped in quote marks -- no hook, no line
breaks, no hashtags -- markedly worse than the text-only writer it replaced.

So the two jobs are split. A vision model looks at the image once and writes a
plain description; the normal writer then works from that description as if the
user had typed it. The vision cost is paid only when an image is attached, and
the model that shapes the copy never changes.

Configured with ``VISION_DESCRIBE_MODEL``. Empty disables the step, in which
case an image attached to a text-only model is reported rather than silently
ignored.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProviderError
from app.llm.registry import get_llm_provider

logger = get_logger(__name__)

#: Deliberately short.
#:
#: Measured: a small vision model is not an instruction-follower. moondream
#: (1.8B) returned an EMPTY response to a multi-clause prompt with negations
#: ("cover X, Y, Z; do not write marketing copy; do not give advice; max 90
#: words") and a complete, accurate description to plain "Describe this image."
#: -- reading the banner text, counting the shapes and naming the colours.
#: Elaborate prompting here buys nothing and silently loses the description.
#:
#: Keeping the model to pure description also keeps marketing phrasing out of
#: the text, which matters because the writer downstream treats this as fact.
_PROMPT = "Describe this image."

#: A description longer than this is padding, and it displaces the profile and
#: memories in the writer's context window.
_MAX_CHARS = 700


def describe_model() -> str:
    return str(getattr(settings, "VISION_DESCRIBE_MODEL", "") or "").strip()


def can_describe() -> bool:
    return bool(describe_model())


def describe_images(images: list[str], *, request: str = "") -> str | None:
    """Return a text description of ``images``, or ``None`` if unavailable.

    Never raises: a failed description must degrade to "no description" rather
    than losing the user's turn, because the request is still answerable
    without it.
    """
    model = describe_model()
    if not model or not images:
        return None

    # The request is deliberately NOT appended. Adding task context made the
    # prompt multi-clause, which is exactly what produced empty responses.
    try:
        response = get_llm_provider().generate(
            [ChatMessage(role="user", content=_PROMPT, images=list(images))],
            temperature=0.0,  # description, not invention
            # Measured descriptions run ~330 characters, so ~90 tokens. 160 is
            # ample headroom, and every token not generated is time saved on a
            # CPU -- the old 320 was paying for output that gets truncated at
            # _MAX_CHARS anyway.
            max_tokens=160,
            model=model,
        )
    except LLMProviderError as exc:
        logger.warning("image description failed on %s: %s", model, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - never lose the turn over this
        logger.warning("image description errored on %s: %s", model, exc)
        return None

    text = " ".join((response.content or "").split())
    if not text:
        logger.warning("image description on %s returned nothing", model)
        return None
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    logger.info("described %d image(s) via %s (%d chars)", len(images), model, len(text))
    return text


__all__ = ["can_describe", "describe_images", "describe_model"]
