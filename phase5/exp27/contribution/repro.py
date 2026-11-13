"""Run the known full-context boundary against the installed native recipe library.

Offline: uses the existing, hash-checked exp19 tokenizer. Context limits are
synthetic test inputs; prompt_tokens is obtained from actual native encoding.
Writes JSON only to stdout. No model, server, or remote resources are used.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys


def main():
    phase5 = Path(__file__).resolve().parents[2]
    tokenizer_path = phase5 / "vendor/minimal/static/tokenizers/v41/tokenizer.json"
    provenance_path = phase5 / "vendor/minimal/tokenizer-provenance.json"
    try:
        from deepseek_recipe import (
            ChatCompletionRequest, ConversionError, ConversionOptions,
            DeepseekV41Encoding, Tokenizer,
        )
        version = importlib.metadata.version("deepseek-recipe")
        tokenizer_bytes = tokenizer_path.read_bytes()
        provenance = json.loads(provenance_path.read_text())
    except (ImportError, FileNotFoundError, importlib.metadata.PackageNotFoundError) as exc:
        print(json.dumps({"status": "environment_missing", "error": str(exc),
                          "expected_python": str(phase5 / ".venv-exp19/bin/python")}))
        return 2
    digest = hashlib.sha256(tokenizer_bytes).hexdigest()
    expected = next(item for item in provenance["files"] if item["version"] == "v41")
    if digest != expected["sha256"]:
        raise RuntimeError("Existing tokenizer does not match exp19 provenance")
    body = {"model": "DeepSeek-V4.1-Flash", "messages": [
        {"role": "user", "content": "你好，请原样返回 TEXT_OK_19。"}
    ]}
    request = ChatCompletionRequest(body).convert(ConversionOptions())
    encoding = DeepseekV41Encoding().with_tokenizer(
        Tokenizer.from_str(tokenizer_bytes.decode("utf-8"))
    )
    token_ids = encoding.encode(request.conversation)
    prompt_tokens = len(token_ids)
    rows = []
    for requested in (None, 1):
        converted = ChatCompletionRequest(
            body if requested is None else {**body, "max_tokens": requested}
        ).convert(ConversionOptions())
        assert encoding.encode(converted.conversation) == token_ids
        for remaining in (-1, 0, 1):
            context_limit = prompt_tokens + remaining
            row = {"requested_max_tokens": requested, "prompt_tokens": prompt_tokens,
                   "context_limit": context_limit, "remaining": remaining}
            try:
                row.update(outcome="returned", value=converted.resolve_max_tokens(
                    prompt_tokens, context_limit))
            except ConversionError as exc:
                row.update(outcome="ConversionError", status_code=exc.status_code,
                           error=str(exc), error_body=exc.body)
            rows.append(row)
    result = {
        "status": "observed", "recipe_version": version,
        "python": sys.version, "executable": sys.executable,
        "request": body, "tokenizer_path": str(tokenizer_path),
        "tokenizer_sha256": digest, "token_ids": token_ids,
        "input_kind": "real_native_conversion_and_encoding; synthetic_context_limits",
        "model_calls": 0, "backend_dispatched": False, "rows": rows,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
