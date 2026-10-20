"""Provider metadata capture — the fields token counts alone cannot give.

Written after noticing the corpus could say how many tokens a run used but not
which model actually served it, whether the response was truncated, or what it
cost in dollars. Each test pins one of those.
"""
from litellm.types.utils import Choices, Message, ModelResponse, Usage

from harnessbench.trace import _response_metadata


def _resp(**kw):
    r = ModelResponse(
        id=kw.get("id", "chatcmpl-x"),
        created=1754500000,
        model=kw.get("model", "gpt-4o-2024-08-06"),
        system_fingerprint=kw.get("fp", "fp_abc"),
        choices=[Choices(finish_reason=kw.get("finish", "stop"), index=0,
                         message=Message(role="assistant", content="hi"))],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    r._hidden_params = kw.get("hidden", {})
    return r


def test_captures_model_that_actually_served():
    """Requesting 'gpt-4o' can be served by a dated snapshot. A corpus that
    records only the requested name silently mixes snapshots."""
    assert _response_metadata(_resp(model="gpt-4o-2024-08-06"))["model_served"] \
        == "gpt-4o-2024-08-06"


def test_truncation_is_flagged_not_just_recorded():
    """finish_reason 'length' means the answer was CUT OFF. That is a failure
    that otherwise reads as a terse response."""
    m = _response_metadata(_resp(finish="length"))
    assert m["finish_reason"] == "length"
    assert m["was_truncated"] is True


def test_normal_stop_is_not_truncation():
    m = _response_metadata(_resp(finish="stop"))
    assert m["was_truncated"] is False


def test_provider_cost_is_preferred_over_computed():
    m = _response_metadata(_resp(hidden={"response_cost": 0.0071}))
    assert m["response_cost"] == 0.0071


def test_missing_fields_are_absent_not_zero():
    """A provider that returns no cost must leave the key out. Zero would be
    a wrong number; absence is an honest gap."""
    r = ModelResponse(choices=[], usage=None)
    r._hidden_params = {}
    m = _response_metadata(r)
    assert "was_truncated" not in m, "no choices means truncation is unknown"
    assert m.get("response_cost", None) != 0


def test_never_raises_on_a_degenerate_response():
    """Bookkeeping must never break a run that already produced an answer."""
    class Weird:
        pass
    assert isinstance(_response_metadata(Weird()), dict)
