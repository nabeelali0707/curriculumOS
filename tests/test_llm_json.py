import json

import pytest

from app.llm_json import loads_llm_json


def test_plain_json():
    assert loads_llm_json('{"a": 1}') == {"a": 1}


def test_markdown_fenced_json():
    """What models actually return when asked for "JSON only" — this exact
    wrapping is why this module exists.
    """
    assert loads_llm_json('```json\n{"nodes": [1, 2]}\n```') == {"nodes": [1, 2]}


def test_bare_fence_without_language_tag():
    assert loads_llm_json('```\n{"a": 1}\n```') == {"a": 1}


def test_json_with_surrounding_prose():
    assert loads_llm_json('Sure! Here is the result:\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_top_level_list():
    assert loads_llm_json("```json\n[1, 2, 3]\n```") == [1, 2, 3]


def test_unparseable_raises_json_error_so_callers_can_fail_the_batch():
    with pytest.raises(json.JSONDecodeError):
        loads_llm_json("I'm afraid I can't help with that.")
