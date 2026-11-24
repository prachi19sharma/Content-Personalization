"""Strip scaffolding so copy can be pasted straight into a post box.

A caption agent's deliverable is text the user pastes. Anything else in the
reply -- a "Headline:" label, a "Why this works" explainer, a cheerful
preamble, quotation marks wrapped around the whole thing -- has to be deleted by
hand before use, every single time.

Asking the model not to do it is necessary but not sufficient. Measured on
``llama3.2:3b``: it emitted "Headline:" and "Body:" labels and a "Why this
works:" section. (The explainer was actually in the prompt, which is fixed; the
labels never were.) This is the same finding as the scope and grounding guards
-- a small model does not reliably honour negative instructions -- so the same
answer applies: check it in code.

Unlike the grounding guard this one *rewrites*, because the failure mode is
different. A fabricated figure cannot be deleted without wrecking the sentence
around it, so that guard flags. A label prefix is removable with no loss to the
copy, so removing it is strictly better than telling the user to do it.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Field labels a model invents when it thinks in terms of a form. Matched only
#: at the start of a line, so a sentence mentioning "the hook:" is untouched.
_LABELS = (
    "headline",
    "hook",
    "body",
    "body copy",
    "caption",
    "cta",
    "call to action",
    "post",
    "copy",
    "text",
    "hashtags",
)
#: ``[ \t]*`` after the colon, not ``\s*``: ``\s`` includes the newline, so a
#: label on its own line ("Body:\n") swallowed the line break and welded the
#: paragraphs together -- destroying exactly the spacing that makes a caption
#: readable.
_LABEL_RE = re.compile(
    r"^[ \t]*(?:\*\*|__|\*)?(" + "|".join(_LABELS) + r")(?:\*\*|__|\*)?[ \t]*:[ \t]*",
    re.IGNORECASE | re.MULTILINE,
)

#: Trailing meta-commentary. Everything from the heading to the end goes: the
#: model puts its reasoning last, and it is never part of the deliverable.
_META_HEADINGS = (
    "why this works",
    "why it works",
    "rationale",
    "explanation",
    "notes?",
    "note",
    "reasoning",
    "breakdown",
    "strategy",
)
_META_RE = re.compile(
    r"\n\s*(?:\*\*|__|#{1,6}\s*)?(?:" + "|".join(_META_HEADINGS) + r")(?:\*\*|__)?\s*:?\s*\n.*$",
    re.IGNORECASE | re.DOTALL,
)

#: Conversational wrappers before the copy, stripped in two passes because they
#: compose: "Sure! Here is your caption:" is an interjection *and* an
#: announcement, and one pattern trying to match both either missed it or
#: matched a bare newline and ate real leading blank lines.
_INTERJECTION_RE = re.compile(
    r"^[ \t]*(?:sure|certainly|of course|absolutely|no problem|got it)[!,.…]*[ \t]*",
    re.IGNORECASE,
)
#: An announcement line: short, ends the line, and never part of the copy.
_ANNOUNCE_RE = re.compile(
    r"^[ \t]*(?:here(?:'s| is| are)|below is|i'?ve (?:written|drafted|put together)|"
    r"i'?d be happy to)[^\n]{0,80}:[ \t]*\n+",
    re.IGNORECASE,
)


def _unwrap_quotes(text: str) -> str:
    """Drop quote marks wrapping the whole reply.

    Only when they enclose everything: a caption that legitimately quotes
    someone mid-sentence must keep its quotes.
    """
    stripped = text.strip()
    pairs = (('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u2018", "\u2019"))
    for opener, closer in pairs:
        if len(stripped) > 2 and stripped.startswith(opener) and stripped.endswith(closer):
            inner = stripped[1:-1]
            # If the inner text still contains that quote character, the outer
            # pair was probably real punctuation rather than a wrapper.
            if opener not in inner and closer not in inner:
                return inner.strip()
    return stripped


def make_paste_ready(text: str) -> tuple[str, list[str]]:
    """Return ``(cleaned, removed)``; ``removed`` names what was stripped."""
    if not text or not text.strip():
        return text, []

    removed: list[str] = []
    cleaned = text

    without_meta = _META_RE.sub("", cleaned)
    if without_meta != cleaned:
        removed.append("explanatory section")
        cleaned = without_meta

    without_preamble = _ANNOUNCE_RE.sub("", _INTERJECTION_RE.sub("", cleaned))
    # Run once more: stripping "Sure! " can expose the announcement that
    # followed it on the same line.
    without_preamble = _ANNOUNCE_RE.sub("", without_preamble)
    if without_preamble.strip() and without_preamble != cleaned:
        removed.append("preamble")
        cleaned = without_preamble

    without_labels = _LABEL_RE.sub("", cleaned)
    if without_labels != cleaned:
        removed.append("field labels")
        cleaned = without_labels

    unwrapped = _unwrap_quotes(cleaned)
    if unwrapped != cleaned.strip():
        removed.append("wrapping quotes")
        cleaned = unwrapped

    # A label alone on its line leaves an empty line behind once removed. Drop
    # those, then collapse any run of blank lines to exactly one -- keeping the
    # single blank lines that give a caption its shape.
    cleaned = re.sub(r"(?m)^[ \t]+$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if removed:
        logger.info("paste-ready cleanup removed: %s", ", ".join(removed))
    return cleaned, removed


__all__ = ["make_paste_ready"]
