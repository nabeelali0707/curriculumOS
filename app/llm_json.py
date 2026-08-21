"""Parsing JSON out of an LLM response.

"Respond with JSON only" is a request, not a guarantee. Real models wrap
the object in ```json fences, prepend a sentence of preamble, or (for
thinking models) emit reasoning first. Every place that asks an LLM for
structured output hits this, so the unwrapping lives here once rather than
being re-solved — differently, and wrongly — in each parser.
"""

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def loads_llm_json(raw_text: str) -> object:
    """json.loads, tolerant of the wrapping models actually produce.

    Raises json.JSONDecodeError (like json.loads) when nothing in the text
    parses — callers already treat that as "don't guess, fail the batch".
    """
    text = raw_text.strip()

    candidates = [text]
    fenced = _FENCE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1))
    # Last resort: the outermost {...} or [...] in the text, for responses
    # that put prose around bare (unfenced) JSON.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            candidates.append(text[start : end + 1])

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    assert last_error is not None  # candidates is never empty
    raise last_error
