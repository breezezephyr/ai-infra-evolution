"""Characterize existing native behavior, without claiming backend capacity.

These are deliberately synthetic token counts, independent of tokenizing 'hi'.
The identical test function is included in the proposed upstream patch.
"""
import pytest
from deepseek_recipe import ChatCompletionRequest, ConversionError, ConversionOptions


@pytest.mark.parametrize("max_tokens", [None, 1])
@pytest.mark.parametrize("remaining", [-1, 0, 1])
def test_resolve_max_tokens_at_full_context_boundary(max_tokens, remaining):
    body = {"model": "DeepSeek-V4.1-Flash", "messages": [{"role": "user", "content": "hi"}]}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    request = ChatCompletionRequest(body).convert(ConversionOptions())
    # Synthetic counts: exercise the helper independently of prompt encoding.
    prompt_tokens = 100
    context_limit = prompt_tokens + remaining
    if remaining < 0 or (remaining == 0 and max_tokens is not None):
        with pytest.raises(ConversionError, match="maximum context length") as rejected:
            request.resolve_max_tokens(prompt_tokens, context_limit)
        assert rejected.value.status_code == 400
    else:
        # An omitted limit retains the documented floor even with zero capacity.
        assert request.resolve_max_tokens(prompt_tokens, context_limit) == 1
