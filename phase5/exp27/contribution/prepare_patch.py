"""Prepare a docs/test-only patch from the archived official GitHub snapshot."""
import difflib
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
BASE = HERE / "evidence/upstream-current"
PATCHED = HERE / "patched-upstream"


def main():
    en = "docs/tokenizer.md"
    zh = "docs/tokenizer.zh.md"
    tests = "deepseek-recipe-python/tests/test_bindings.py"
    originals = {name: (BASE / name).read_text() for name in (en, zh, tests)}
    old = "otherwise, lowered to the context left after the prompt. The method returns a"
    new = ("otherwise, lowered to the context left after the prompt and raised to at least\n"
           "1. The method returns a")
    assert originals[en].count(old) == 1
    changed = {en: originals[en].replace(old, new)}
    anchor = "exceed `context_limit`.\n"
    warning = (
        "\nWhen no `max_tokens` is requested and `prompt_tokens == context_limit`, the\n"
        "method returns 1 because of this floor, even though no context remains.\n"
        "At the same boundary, an explicit `max_tokens` of 1 raises `ConversionError`.\n"
        "Callers that require space for output must check for a full context before\n"
        "dispatching to their backend; a positive return value alone is insufficient.\n"
    )
    assert changed[en].count(anchor) == 1
    changed[en] = changed[en].replace(anchor, anchor + warning)
    old_zh = "并降到 prompt 之后剩余的上下文以内。"
    new_zh = "并降到 prompt 之后剩余的上下文以内，再抬高到至少 1。"
    assert originals[zh].count(old_zh) == 1
    changed[zh] = originals[zh].replace(old_zh, new_zh)
    anchor_zh = "prompt 与请求的 `max_tokens` 之和超过 `context_limit` 时，该方法返回 `ConversionError`。\n"
    warning_zh = (
        "\n未指定 `max_tokens` 且 `prompt_tokens == context_limit` 时，即使上下文已满，"
        "该方法仍因最小值规则返回 1；同一边界显式请求 `max_tokens=1` 则抛出 `ConversionError`。"
        "需要为输出预留空间的调用方应在下发后端前检查上下文是否已满，不能仅以返回值为正作为依据。\n"
    )
    assert changed[zh].count(anchor_zh) == 1
    changed[zh] = changed[zh].replace(anchor_zh, anchor_zh + warning_zh)
    test_function = (HERE / "test_context_budget.py").read_text().split("@pytest.mark.parametrize", 1)[1]
    test_function = "@pytest.mark.parametrize" + test_function
    test_anchor = "def test_max_tokens_upper_bound_rejects_or_clamps():"
    assert originals[tests].count(test_anchor) == 1
    changed[tests] = originals[tests].replace(test_anchor, test_function + "\n\n" + test_anchor)
    patch = "".join(
        "".join(difflib.unified_diff(originals[name].splitlines(True),
                                    changed[name].splitlines(True),
                                    fromfile="a/" + name, tofile="b/" + name))
        for name in (en, zh, tests)
    )
    (HERE / "patch.diff").write_text(patch)
    # A disposable local copy, always within the authorized contribution folder.
    shutil.copytree(BASE, PATCHED, dirs_exist_ok=True)
    print("patch.diff: two tokenizer guides and six native binding boundary cases")


if __name__ == "__main__":
    main()
