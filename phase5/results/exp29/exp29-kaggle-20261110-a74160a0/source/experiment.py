#!/usr/bin/env python3
"""Bounded, loopback-only Qwen3 FP16 text experiment (not a serving benchmark).

Python >=3.12. GPU dependencies: existing torch, transformers==4.51.3,
safetensors, fastapi, uvicorn. CPU parser tests need only stdlib.
Model loading is local_files_only; this file never downloads models.

Example (preparation files may already exist in OUT):
  python experiment.py --out-dir /kaggle/working/exp29-kaggle-20261110-a74160a0 \
      --run-id exp29-kaggle-20261110-a74160a0 --served-model qwen3-4b
--model-path overrides OUT/model-prepared.json's model_path.

Exactly five planned POSTs, serial, no retries. At most three generate calls;
max_new_tokens reservations are 32+32+1=65, including EOS in native counts.
Only the spawned child loads CUDA; cleanup terminates only that child.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import codecs
import copy
import hashlib
import http.client
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import re
import socket
import sys
import threading
import time
import traceback
import uuid


GENERATION_SECONDS = 90
REQUEST_SECONDS = 120
MESSAGES = [{"role": "user", "content": "请用一句简短的中文解释天空为什么通常是蓝色的。"}]
SEED = 29


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class SSEProtocolError(ValueError):
    pass


class SSEParser:
    """Incremental UTF-8 SSE framing and strict single-choice chat termination.

    raw preserves every byte supplied, including a chunk causing an error.
    Fragments are HTTP entity reads, not assertions about TCP packet boundaries.
    finish requires finish -> usage -> DONE and a terminated final SSE event.
    """
    def __init__(self):
        self.raw = bytearray()
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.pending = ""
        self.data = []
        self.event = ""
        self.events = []
        self.text = ""
        self.finish_reason = None
        self.usage = None
        self.done = False

    def feed(self, chunk):
        self.raw.extend(chunk)
        before = len(self.events)
        try:
            self.pending += self.decoder.decode(chunk)
            self._lines(final=False)
        except UnicodeError as exc:
            raise SSEProtocolError("invalid UTF-8") from exc
        return self.events[before:]

    def _lines(self, final):
        while True:
            match = re.search(r"\r\n|\r|\n", self.pending)
            if match is None:
                return
            if match.group() == "\r" and match.end() == len(self.pending) and not final:
                return  # May be the first half of a CRLF across reads.
            line = self.pending[:match.start()]
            self.pending = self.pending[match.end():]
            if not line:
                self._dispatch()
            elif not line.startswith(":"):
                field, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if field == "data":
                    self.data.append(value)
                elif field == "event":
                    self.event = value

    def _dispatch(self):
        event, data = self.event, self.data
        self.event, self.data = "", []
        if not data:
            return
        payload = "\n".join(data)
        if self.done:
            raise SSEProtocolError("data after DONE")
        if event == "error":
            raise SSEProtocolError("server error event: " + payload)
        if payload == "[DONE]":
            if self.finish_reason is None or self.usage is None:
                raise SSEProtocolError("DONE before finish and usage")
            self.done = True
            self.events.append(payload)
            return
        try:
            value = json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise SSEProtocolError("invalid JSON event") from exc
        self.events.append(value)
        if not isinstance(value, dict) or "error" in value:
            raise SSEProtocolError("invalid/error JSON event")
        choices = value.get("choices")
        if value.get("usage") is not None:
            usage = value["usage"]
            if choices != [] or self.finish_reason is None or self.usage is not None:
                raise SSEProtocolError("usage must occur once, after finish, with empty choices")
            keys = ("prompt_tokens", "completion_tokens", "total_tokens")
            if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys):
                raise SSEProtocolError("invalid usage counts")
            if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
                raise SSEProtocolError("inconsistent usage sum")
            self.usage = usage
            return
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise SSEProtocolError("expected exactly one choice")
        choice = choices[0]
        delta = choice.get("delta")
        if choice.get("index") != 0 or not isinstance(delta, dict):
            raise SSEProtocolError("invalid choice/delta")
        if self.finish_reason is not None:
            raise SSEProtocolError("choice after finish")
        content = delta.get("content", "")
        if not isinstance(content, str):
            raise SSEProtocolError("non-string content")
        self.text += content
        reason = choice.get("finish_reason")
        if reason is not None:
            if reason not in ("stop", "length"):
                raise SSEProtocolError("invalid finish reason")
            self.finish_reason = reason

    def finish(self):
        try:
            self.pending += self.decoder.decode(b"", final=True)
            self._lines(final=True)
        except UnicodeError as exc:
            raise SSEProtocolError("incomplete UTF-8 at EOF") from exc
        if self.pending or self.data or self.event:
            raise SSEProtocolError("unterminated SSE event at EOF")
        if not self.done or self.finish_reason is None or self.usage is None:
            raise SSEProtocolError("missing finish/usage/DONE at EOF")


def plan_requests(run_id, alias):
    plan = []
    cases = [("missing-model", alias + "-nonexistent", 32, False, 404),
             ("over-limit", alias, 65, False, 422),
             ("nonstream", alias, 32, False, 200),
             ("stream", alias, 32, True, 200),
             ("one-token", alias, 1, False, 200)]
    for case, model, limit, stream, status in cases:
        body = dict(model=model, messages=MESSAGES, max_tokens=limit,
                    stream=stream, temperature=0, seed=SEED)
        if stream:
            body["stream_options"] = {"include_usage": True}
        plan.append(dict(case_id=case, client_request_id=run_id + ":" + case,
                         expected_status=status, body=body, body_sha256=sha(json_bytes(body))))
    return plan


def serve_child(settings, ready, shutdown):
    """Only this owned process imports torch and owns GPU0 allocations."""
    out = Path(settings["out_dir"])
    lock = threading.RLock()
    env = {"python": sys.version, "pid": os.getpid(), "backend": "transformers.generate",
           "served_model": settings["served_model"], "model_path": settings["model_path"],
           "execution": "single GPU0, FP16, serial; no vLLM/DeepInfer/continuous batching",
           "clock_domain": f"server-{os.getpid()}:monotonic_ns",
           "timing_note": "instrumented wall time within this process; never subtract client clocks"}
    ledger = dict(max_generate_calls=3, max_reserved_output_tokens=65,
                  generate_calls=0, reserved_output_tokens=0, completed_generations=0,
                  actual_output_tokens=0, native_output_unknown=False, http_requests=0)

    def ledger_save():
        save(out / "budget.json", ledger)

    def patch(record, **fields):
        with lock:
            record.update(fields)
            save(out / "server" / (record["request_id"] + ".json"), record)

    try:
        import torch
        import transformers
        import fastapi
        import uvicorn
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, StreamingResponse
        from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer, StoppingCriteria

        # Request is local to this function; FastAPI resolves postponed annotations globally.
        globals()["Request"] = Request
        env.update(torch=torch.__version__, transformers=transformers.__version__,
                   fastapi=fastapi.__version__, uvicorn=uvicorn.__version__,
                   cuda_runtime=torch.version.cuda, cuda_available=torch.cuda.is_available())
        save(out / "environment.json", env)
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU0 is required; CPU fallback is forbidden")
        torch.cuda.set_device(0)

        def memory():
            free, total = torch.cuda.mem_get_info(0)
            return dict(device="cuda:0", allocated_bytes=torch.cuda.memory_allocated(0),
                        reserved_bytes=torch.cuda.memory_reserved(0),
                        peak_allocated_bytes=torch.cuda.max_memory_allocated(0),
                        peak_reserved_bytes=torch.cuda.max_memory_reserved(0),
                        device_free_bytes=free, device_total_bytes=total,
                        device_free_scope="whole GPU; may include other processes",
                        allocator_scope="this server process only")

        properties = torch.cuda.get_device_properties(0)
        env.update(gpu0=dict(name=properties.name, total_memory_bytes=properties.total_memory,
                            capability=list(torch.cuda.get_device_capability(0))),
                   visible_gpu_count=torch.cuda.device_count(), gpu_memory_before_load=memory())
        model_dir = Path(settings["model_path"])
        env["model_files"] = [{"path": str(p.relative_to(model_dir)), "bytes": p.stat().st_size,
                               "sha256": file_sha(p)}
                              for p in sorted(model_dir.rglob("*")) if p.is_file()]
        if not env["model_files"]:
            raise RuntimeError("model directory contains no files")
        env["source_files"] = [{"path": str(p), "sha256": file_sha(p)}
                               for p in (Path(__file__).resolve(), Path(__file__).with_name("test_sse.py")) if p.is_file()]
        save(out / "environment.json", env)
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
        env.update(chat_template=tokenizer.chat_template,
                   template_options={"enable_thinking": False, "add_generation_prompt": True},
                   rendered_template=tokenizer.apply_chat_template(
                       MESSAGES, tokenize=False, add_generation_prompt=True, enable_thinking=False))
        save(out / "environment.json", env)
        model = AutoModelForCausalLM.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=False,
            torch_dtype=torch.float16, use_safetensors=True, attn_implementation="eager")
        if model.config.model_type != "qwen3":
            raise RuntimeError("expected native Qwen3 architecture")
        model = model.to("cuda:0").eval()
        torch.cuda.synchronize(0)
        env.update(model_config=model.config.to_dict(), parameter_count=sum(p.numel() for p in model.parameters()),
                   parameter_devices=sorted({str(p.device) for p in model.parameters()}),
                   parameter_dtypes=sorted({str(p.dtype) for p in model.parameters()}),
                   gpu_memory_after_load=memory(), implementation_files=[])
        if env["parameter_devices"] != ["cuda:0"] or env["parameter_dtypes"] != ["torch.float16"]:
            raise RuntimeError("model must reside entirely on GPU0 in FP16")
        for method in (model.generate, TextIteratorStreamer.put, tokenizer.apply_chat_template):
            path = inspect.getsourcefile(method)
            env["implementation_files"].append(dict(method=method.__qualname__, path=path,
                                                     sha256=file_sha(path) if path else None))
        save(out / "environment.json", env)
        ledger_save()
        generation_gate = threading.Lock()

        class Cancel(StoppingCriteria):
            def __init__(self, event, deadline):
                self.event, self.deadline = event, deadline

            def __call__(self, input_ids, scores, **kwargs):
                return self.event.is_set() or time.monotonic() > self.deadline

        def start_generation(record, body):
            cancel, done, result = threading.Event(), threading.Event(), {}
            callbacks = []

            class ObservedStreamer(TextIteratorStreamer):
                def put(self, value):
                    entry = time.monotonic_ns()
                    is_prompt = self.next_tokens_are_prompt
                    if not is_prompt:
                        ids = value.detach().cpu().reshape(-1).tolist()
                        callbacks.append(dict(token_ids=ids, rel_ns=entry - result["started_ns"]))
                        patch(record, token_callbacks=list(callbacks),
                              first_token_callback_rel_ns=callbacks[0]["rel_ns"])
                    super().put(value)

            streamer = ObservedStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True,
                                         clean_up_tokenization_spaces=False, timeout=0.1)

            def worker():
                try:
                    rendered = tokenizer.apply_chat_template(body["messages"], tokenize=False,
                                                             add_generation_prompt=True, enable_thinking=False)
                    inputs = tokenizer.apply_chat_template(body["messages"], tokenize=True, return_tensors="pt",
                                                           return_dict=True, add_generation_prompt=True,
                                                           enable_thinking=False)
                    input_ids = inputs["input_ids"][0].tolist()
                    if len(input_ids) > 1024:
                        raise RuntimeError("input token safety limit exceeded")
                    inputs = {k: v.to("cuda:0") for k, v in inputs.items()}
                    config = copy.deepcopy(model.generation_config)
                    config.do_sample, config.num_beams, config.num_return_sequences = False, 1, 1
                    config.temperature = config.top_p = config.top_k = None
                    config.max_new_tokens, config.return_dict_in_generate = body["max_tokens"], True
                    if config.pad_token_id is None:
                        eos = config.eos_token_id
                        config.pad_token_id = eos[0] if isinstance(eos, list) else eos
                    torch.random.default_generator.manual_seed(body["seed"])
                    torch.cuda.manual_seed(body["seed"])  # Current GPU0 only, not manual_seed_all.
                    torch.cuda.synchronize(0)
                    patch(record, native_state="prepared", rendered_template=rendered,
                          rendered_template_sha256=sha(rendered.encode("utf-8")),
                          input_token_ids=input_ids, generation_config=config.to_dict(),
                          gpu_memory_before_generation=memory())
                    with lock:
                        if ledger["generate_calls"] >= 3 or ledger["reserved_output_tokens"] + body["max_tokens"] > 65:
                            raise RuntimeError("hard generation reservation budget exceeded")
                        ledger["generate_calls"] += 1
                        ledger["reserved_output_tokens"] += body["max_tokens"]
                        ledger_save()
                    result["started_ns"] = time.monotonic_ns()
                    patch(record, native_state="generating", generate_started_ns=result["started_ns"])
                    with torch.inference_mode():
                        generated = model.generate(**inputs, generation_config=config, streamer=streamer,
                                                   stopping_criteria=[Cancel(cancel, time.monotonic() + GENERATION_SECONDS)])
                    torch.cuda.synchronize(0)
                    total_ns = time.monotonic_ns() - result["started_ns"]
                    # Native IDs exclusively from generate.sequences; never re-encode output text.
                    sequences = generated.sequences.detach().cpu()
                    if sequences.shape[0] != 1 or sequences[0, :len(input_ids)].tolist() != input_ids:
                        raise RuntimeError("generate returned an unexpected sequence/prompt")
                    output_ids = sequences[0, len(input_ids):].tolist()
                    text = tokenizer.decode(output_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)
                    eos_ids = config.eos_token_id
                    eos_ids = eos_ids if isinstance(eos_ids, list) else [eos_ids]
                    if cancel.is_set():
                        reason = "cancelled"
                    elif output_ids and output_ids[-1] in eos_ids:
                        reason = "stop"
                    elif len(output_ids) == body["max_tokens"]:
                        reason = "length"
                    else:
                        reason = "unexpected_stop"
                    usage = dict(prompt_tokens=len(input_ids), completion_tokens=len(output_ids),
                                 total_tokens=len(input_ids) + len(output_ids))
                    with lock:
                        ledger["completed_generations"] += 1
                        ledger["actual_output_tokens"] += len(output_ids)
                        ledger_save()
                    patch(record, native_state="completed", output_token_ids=output_ids,
                          output_ids_source="generate.sequences[0, actual_input_length:]",
                          text=text, native_usage=usage, finish_reason=reason,
                          eos_token_ids=eos_ids, output_count_includes_eos=True,
                          generate_total_ns=total_ns, gpu_memory_after_generation=memory(),
                          token_callbacks=list(callbacks))
                    callback_ids = [x for item in callbacks for x in item["token_ids"]]
                    if not output_ids or len(output_ids) > body["max_tokens"] or callback_ids != output_ids:
                        raise RuntimeError("native output/callback/budget reconciliation failed")
                    if reason not in ("stop", "length"):
                        raise RuntimeError("generation did not reach a valid native terminal: " + reason)
                    result.update(text=text, usage=usage, finish_reason=reason)
                except BaseException as exc:
                    result["error"] = f"{type(exc).__name__}: {exc}"
                    with lock:
                        if "started_ns" in result and "output_token_ids" not in record:
                            ledger["native_output_unknown"] = True
                            ledger_save()
                    patch(record, native_state="error", error=result["error"], traceback=traceback.format_exc(),
                          token_callbacks=list(callbacks), gpu_memory_on_error=memory())
                    # Release a consumer even if generate never called streamer.end().
                    streamer.on_finalized_text("", stream_end=True)
                finally:
                    generation_gate.release()
                    done.set()

            thread = threading.Thread(target=worker, name="exp29-generate", daemon=True)
            thread.start()
            return streamer, thread, done, cancel, result

        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.post("/v1/chat/completions")
        async def completions(request: Request):
            started = time.monotonic_ns()
            raw = await request.body()
            rid = uuid.uuid4().hex
            client_id = request.headers.get("x-client-request-id")
            try:
                body = json.loads(raw)
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            record = dict(request_id=rid, client_request_id=client_id, run_id=settings["run_id"],
                          clock_domain=env["clock_domain"], request_started_ns=started,
                          body_utf8=raw.decode("utf-8", errors="replace"), body_sha256=sha(raw),
                          prompt_sha256=sha(json_bytes(body.get("messages"))),
                          requested_model=body.get("model"), loaded_model_alias=settings["served_model"],
                          native_state="not_run", token_callbacks=[])
            headers = {"X-Request-Id": rid, "X-Client-Request-Id": client_id or "",
                       "X-Run-Id": settings["run_id"]}
            metadata = dict(id="chatcmpl-" + rid, request_id=rid, client_request_id=client_id,
                            run_id=settings["run_id"], model=body.get("model"),
                            body_sha256=sha(raw), prompt_sha256=record["prompt_sha256"])
            with lock:
                ledger["http_requests"] += 1
                ledger_save()
            patch(record)

            def reject(status, code, message):
                patch(record, http_status=status, rejection_code=code,
                      request_total_ns=time.monotonic_ns() - started)
                return JSONResponse(dict(**metadata, error=dict(code=code, message=message)),
                                    status_code=status, headers=headers)

            if ledger["http_requests"] > 5:
                return reject(429, "request_budget", "five-request budget exhausted")
            if body.get("model") != settings["served_model"]:
                return reject(404, "model_not_found", "unknown served model alias")
            if type(body.get("max_tokens")) is not int or not 1 <= body["max_tokens"] <= 64:
                return reject(422, "token_limit", "max_tokens must be an integer in [1,64]")
            if (body.get("messages") != MESSAGES or body.get("temperature") != 0 or
                    type(body.get("seed")) is not int or body["seed"] != SEED or
                    type(body.get("stream")) is not bool):
                return reject(422, "controlled_input", "request is outside the fixed experiment")
            if body["stream"] and body.get("stream_options") != {"include_usage": True}:
                return reject(422, "stream_options", "include_usage is required")
            if not generation_gate.acquire(blocking=False):
                return reject(409, "serial_only", "a generation is already in progress")
            streamer, thread, done, cancel, result = start_generation(record, body)

            def chunk(delta, reason=None):
                return dict(**metadata, object="chat.completion.chunk",
                            choices=[dict(index=0, delta=delta, finish_reason=reason)])

            def sse(value):
                return b"data: " + json_bytes(value) + b"\n\n"

            if not body["stream"]:
                try:
                    completed = await asyncio.to_thread(done.wait, GENERATION_SECONDS + 5)
                    if not completed or "error" in result:
                        raise RuntimeError(result.get("error", "generation deadline exceeded"))
                    response = dict(**metadata, object="chat.completion", usage=result["usage"],
                                    choices=[dict(index=0, message=dict(role="assistant", content=result["text"]),
                                                  finish_reason=result["finish_reason"])])
                    patch(record, http_status=200, request_total_ns=time.monotonic_ns() - started)
                    return JSONResponse(response, headers=headers)
                except Exception as exc:
                    return reject(500, "generation_error", str(exc))
                finally:
                    cancel.set()
                    await asyncio.to_thread(thread.join, 2)

            def poll():
                try:
                    return "text", next(streamer)
                except queue.Empty:
                    return "wait", None
                except StopIteration:
                    return "end", None

            async def stream_response():
                stream_text = ""
                try:
                    yield sse(chunk(dict(role="assistant")))
                    deadline = time.monotonic() + GENERATION_SECONDS + 5
                    while True:
                        if time.monotonic() > deadline:
                            raise TimeoutError("stream generation deadline exceeded")
                        if done.is_set() and "error" in result:
                            raise RuntimeError(result["error"])
                        kind, text = await asyncio.to_thread(poll)
                        if kind == "end":
                            break
                        if kind == "text" and text:
                            stream_text += text
                            yield sse(chunk(dict(content=text)))
                    if not await asyncio.to_thread(done.wait, 2) or "error" in result:
                        raise RuntimeError(result.get("error", "worker did not terminate"))
                    if stream_text != result["text"]:
                        raise RuntimeError("stream text differs from native sequence decode")
                    patch(record, http_status=200, streamed_text=stream_text,
                          request_total_ns=time.monotonic_ns() - started)
                    yield sse(chunk({}, result["finish_reason"]))
                    yield sse(dict(**metadata, object="chat.completion.chunk", choices=[], usage=result["usage"]))
                    yield b"data: [DONE]\n\n"
                except Exception as exc:
                    patch(record, stream_error=f"{type(exc).__name__}: {exc}")
                    yield b"event: error\n" + sse(dict(**metadata, error=dict(message=str(exc))))
                finally:
                    cancel.set()
                    await asyncio.to_thread(thread.join, 2)

            return StreamingResponse(stream_response(), media_type="text/event-stream", headers=headers)

        bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            bound.bind(("127.0.0.1", 8765))
        except OSError:
            bound.bind(("127.0.0.1", 0))
        bound.listen(8)
        port = bound.getsockname()[1]

        class ReadyServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    ready.send(dict(ready=True, port=port, pid=os.getpid()))

        server = ReadyServer(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                            access_log=False, timeout_graceful_shutdown=3))

        def watch_shutdown():
            shutdown.wait()
            server.should_exit = True

        threading.Thread(target=watch_shutdown, name="exp29-shutdown", daemon=True).start()
        env.update(port=port, bind_host="127.0.0.1")
        save(out / "environment.json", env)
        try:
            server.run(sockets=[bound])
        finally:
            bound.close()
            env["gpu_memory_before_process_exit"] = memory()
            save(out / "environment.json", env)
    except BaseException as exc:
        env.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        save(out / "environment.json", env)
        try:
            ready.send(dict(ready=False, error=env["error"]))
        except (BrokenPipeError, OSError):
            pass
        raise
    finally:
        ready.close()


def call_http(case, port, out):
    folder = out / "client" / case["case_id"]
    body = json_bytes(case["body"])
    started = time.monotonic_ns()
    row = dict(case_id=case["case_id"], client_request_id=case["client_request_id"],
               body_sha256=sha(body), clock_domain=f"client-{os.getpid()}:monotonic_ns",
               started_ns=started, state="dispatched", status=None, actual_server_request_id=None,
               first_nonempty_content_rel_ns=None, first_content_observation=(
                   "parsed SSE content delta" if case["body"]["stream"] else "content parsed from complete JSON body"),
               fragment_semantics="HTTP response entity read1 chunks; not TCP packets or model tokens")
    save(folder / "result.json", row)
    parser = SSEParser() if case["body"]["stream"] else None
    raw, fragments, payload = bytearray(), [], None
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=REQUEST_SECONDS)
    try:
        connection.request("POST", "/v1/chat/completions", body=body,
                           headers={"Content-Type": "application/json", "Accept-Encoding": "identity",
                                    "X-Client-Request-Id": case["client_request_id"]})
        response = connection.getresponse()
        row.update(status=response.status, reason=response.reason, http_version=response.version,
                   response_headers=response.getheaders(), actual_server_request_id=response.getheader("x-request-id"),
                   echoed_client_request_id=response.getheader("x-client-request-id"),
                   echoed_run_id=response.getheader("x-run-id"),
                   headers_received_rel_ns=time.monotonic_ns() - started)
        with (folder / "response.raw.bin").open("wb") as wire, (folder / "reads.jsonl").open("w", encoding="utf-8") as reads:
            while True:
                remaining = REQUEST_SECONDS - (time.monotonic_ns() - started) / 1_000_000_000
                if remaining <= 0:
                    raise TimeoutError("total HTTP deadline exceeded")
                # HTTPConnection may detach a closing response socket; use its
                # response-owned socket as a fallback to bound every blocking read.
                read_socket = connection.sock
                if read_socket is None and response.fp is not None:
                    read_socket = getattr(getattr(response.fp, "raw", None), "_sock", None)
                if read_socket is not None:
                    read_socket.settimeout(remaining)
                part = response.read1(4096)
                received = time.monotonic_ns() - started
                if not part:
                    break
                fragment = dict(offset=len(raw), bytes=len(part), received_rel_ns=received,
                                base64=base64.b64encode(part).decode("ascii"))
                raw.extend(part)
                wire.write(part)
                wire.flush()
                reads.write(json.dumps(fragment) + "\n")
                reads.flush()
                fragments.append(fragment)
                if parser and response.status == 200:
                    if "parse_error" not in row:
                        try:
                            parser.feed(part)
                        except SSEProtocolError as exc:
                            row["parse_error"] = str(exc)  # Drain and retain the remaining raw bytes.
                    has_content = bool(parser.text)
                else:
                    try:
                        payload = json.loads(raw)
                        has_content = bool(payload.get("choices", [{}])[0].get("message", {}).get("content", ""))
                    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
                        has_content = False
                if has_content and row["first_nonempty_content_rel_ns"] is None:
                    row["first_nonempty_content_rel_ns"] = received
        row["full_duration_ns"] = time.monotonic_ns() - started
        if parser and response.status == 200:
            if "parse_error" not in row:
                try:
                    parser.finish()
                except SSEProtocolError as exc:
                    row["parse_error"] = str(exc)
            row.update(text=parser.text, http_usage=parser.usage, finish_reason=parser.finish_reason,
                       done=parser.done, sse_events=parser.events)
        else:
            payload = json.loads(raw)
            row["response_json"] = payload
            if response.status == 200:
                row.update(text=payload["choices"][0]["message"]["content"], http_usage=payload["usage"],
                           finish_reason=payload["choices"][0]["finish_reason"])
        row["state"] = "received"
    except Exception as exc:
        row.update(state="failed", error=f"{type(exc).__name__}: {exc}",
                   full_duration_ns=time.monotonic_ns() - started)
    finally:
        connection.close()
        row.update(response_raw_sha256=sha(raw), response_raw_bytes=len(raw), read_count=len(fragments))
        save(folder / "result.json", row)
    return row


def reconcile(case, row, out, run_id):
    checks = {}
    rid = row.get("actual_server_request_id")
    checks["http_status"] = row.get("status") == case["expected_status"]
    checks["transport_completed"] = row.get("state") == "received" and "parse_error" not in row
    checks["server_id_present"] = isinstance(rid, str) and re.fullmatch(r"[0-9a-f]{32}", rid) is not None
    checks["echoed_client_id"] = row.get("echoed_client_request_id") == case["client_request_id"]
    checks["echoed_run_id"] = row.get("echoed_run_id") == run_id
    native = None
    if checks["server_id_present"]:
        path = out / "server" / (rid + ".json")
        if path.exists():
            native = json.loads(path.read_text(encoding="utf-8"))
    checks["native_record_present"] = native is not None
    if native:
        expected = dict(request_id=rid, client_request_id=case["client_request_id"], run_id=run_id,
                        body_sha256=case["body_sha256"], prompt_sha256=sha(json_bytes(case["body"]["messages"])))
        for key, value in expected.items():
            checks["native_" + key] = native.get(key) == value
        checks["exact_request_body"] = native.get("body_utf8", "").encode("utf-8") == json_bytes(case["body"])
        checks["requested_model"] = native.get("requested_model") == case["body"]["model"]
        checks["native_http_status"] = native.get("http_status") == case["expected_status"]
        payloads = ([x for x in row.get("sse_events", []) if isinstance(x, dict)]
                    if case["body"]["stream"] and row.get("status") == 200 else [row.get("response_json")])
        checks["payloads_present"] = bool(payloads) and all(isinstance(x, dict) for x in payloads)
        for key, value in dict(**expected, model=case["body"]["model"], id="chatcmpl-" + rid).items():
            checks["http_payload_" + key] = bool(payloads) and all(isinstance(x, dict) and x.get(key) == value for x in payloads)
        if case["expected_status"] != 200:
            checks["rejected_without_generate"] = native.get("native_state") == "not_run" and "generate_started_ns" not in native
            checks["expected_error_code"] = native.get("rejection_code") == (
                "model_not_found" if case["expected_status"] == 404 else "token_limit")
        else:
            ids, inputs = native.get("output_token_ids", []), native.get("input_token_ids", [])
            usage = dict(prompt_tokens=len(inputs), completion_tokens=len(ids), total_tokens=len(inputs) + len(ids))
            checks.update(native_completed=native.get("native_state") == "completed",
                          native_ids_source=native.get("output_ids_source") == "generate.sequences[0, actual_input_length:]",
                          output_limit=0 < len(ids) <= case["body"]["max_tokens"],
                          native_counts=native.get("native_usage") == usage,
                          http_usage=row.get("http_usage") == usage,
                          text=row.get("text") == native.get("text"),
                          finish=row.get("finish_reason") == native.get("finish_reason") and native.get("finish_reason") in ("stop", "length"),
                          actual_callbacks=[x for c in native.get("token_callbacks", []) for x in c["token_ids"]] == ids,
                          native_first_callback=native.get("first_token_callback_rel_ns") is not None,
                          trace_alias=native.get("loaded_model_alias") == case["body"]["model"])
            if case["case_id"] != "one-token":
                checks["nonempty_body_observed"] = bool(row.get("text")) and row.get("first_nonempty_content_rel_ns") is not None
            if case["body"]["stream"]:
                checks["sse_done"] = row.get("done") is True
    row.update(checks=checks, state="passed" if all(checks.values()) else "failed",
               failed_checks=[k for k, passed in checks.items() if not passed])
    save(out / "client" / case["case_id"] / "result.json", row)
    return native


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-path", type=Path, help="local model directory; defaults to OUT/model-prepared.json:model_path")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--served-model", default="qwen3-4b")
    args = parser.parse_args()
    if not args.run_id.strip() or not args.served_model.strip():
        parser.error("run-id and served-model must be nonempty")
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Exclusive, durable marker is never removed: even a failed run cannot regenerate in this OUT.
    marker = out / "experiment.started.json"
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error("experiment.started.json exists; refusing any repeated generation in this output directory")
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(json_bytes(dict(run_id=args.run_id, pid=os.getpid(), source_sha256=file_sha(__file__))))
        handle.flush()
        os.fsync(handle.fileno())
    cases = plan_requests(args.run_id, args.served_model)
    summary = dict(run_id=args.run_id, served_model=args.served_model, backend="transformers.generate",
                   planned_requests=5, planned_generation_requests=3, output_token_reservation_limit=65,
                   dispatched_requests=0, passed_requests=0, technical_contract_pass=False,
                   quality="not_evaluated; one-token completion is budget compliance only",
                   capacity="not_evaluated", billing="not_evaluated", kv_cache="not_evaluated",
                   determinism="no general guarantee; paired serial observation in this run only",
                   requests=[dict(case_id=c["case_id"], state="not_sent") for c in cases])
    save(out / "summary.json", summary)
    child, shutdown, receive = None, None, None
    try:
        # Preparation artifacts are read only. Runner outputs have distinct names.
        for reserved in ("client", "server", "environment.json", "budget.json", "plan.json"):
            if (out / reserved).exists():
                raise RuntimeError("refusing to overwrite runner artifact: " + reserved)
        (out / "client").mkdir()
        (out / "server").mkdir()
        for case in cases:
            folder = out / "client" / case["case_id"]
            folder.mkdir()
            (folder / "request.body.bin").write_bytes(json_bytes(case["body"]))
            save(folder / "request.json", dict(**case, headers={"X-Client-Request-Id": case["client_request_id"],
                                                               "Content-Type": "application/json", "Accept-Encoding": "identity"}))
            save(folder / "result.json", dict(case_id=case["case_id"], state="not_sent"))
        save(out / "plan.json", dict(run_id=args.run_id, cases=cases, retry_count=0, serial=True,
                                    max_generate_calls=3, max_reserved_output_tokens=65))
        if args.model_path is None:
            prepared = json.loads((out / "model-prepared.json").read_text(encoding="utf-8"))
            args.model_path = Path(prepared["model_path"])
        model_path = args.model_path.expanduser().resolve()
        if not model_path.is_dir():
            raise RuntimeError("model-path must be an existing local directory")
        settings = dict(out_dir=str(out), model_path=str(model_path), run_id=args.run_id, served_model=args.served_model)
        context = mp.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        shutdown = context.Event()
        child = context.Process(target=serve_child, args=(settings, send, shutdown), name="exp29-owned-server")
        child.start()
        send.close()
        deadline = time.monotonic() + 900
        while not receive.poll(0.2):
            if not child.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("owned HTTP server failed to become ready within 900s")
        ready = receive.recv()
        if not ready.get("ready"):
            raise RuntimeError(ready.get("error", "server initialization failed"))
        summary.update(server_pid=ready["pid"], bind_host="127.0.0.1", port=ready["port"])
        native_results = {}
        for index, case in enumerate(cases):
            summary["dispatched_requests"] += 1
            summary["requests"][index]["state"] = "dispatched"
            save(out / "summary.json", summary)
            row = call_http(case, ready["port"], out)
            native = reconcile(case, row, out, args.run_id)
            native_results[case["case_id"]] = native
            summary["requests"][index].update(state=row["state"], server_request_id=row.get("actual_server_request_id"),
                                                failed_checks=row.get("failed_checks", []))
            if row["state"] != "passed":
                raise RuntimeError("request failed; no further POSTs: " + case["case_id"])
            summary["passed_requests"] += 1
            if case["case_id"] == "stream":
                left, right = native_results["nonstream"], native_results["stream"]
                observation = dict(scope="two serial requests in this run; no general determinism guarantee",
                                   same_prompt=left["rendered_template"] == right["rendered_template"],
                                   same_input_ids=left["input_token_ids"] == right["input_token_ids"],
                                   same_native_output_ids=left["output_token_ids"] == right["output_token_ids"],
                                   same_text=left["text"] == right["text"])
                summary["paired_serial_observation"] = observation
                if not all(observation[k] for k in ("same_prompt", "same_input_ids", "same_native_output_ids", "same_text")):
                    raise RuntimeError("paired serial observation differs; stopping before final request")
            save(out / "summary.json", summary)
        budget = json.loads((out / "budget.json").read_text(encoding="utf-8"))
        summary["budget"] = budget
        if not (budget["http_requests"] == 5 and budget["generate_calls"] == 3 and
                budget["completed_generations"] == 3 and budget["reserved_output_tokens"] == 65 and
                0 < budget["actual_output_tokens"] <= 65 and not budget["native_output_unknown"]):
            raise RuntimeError("final request/generation/native budget reconciliation failed")
        summary["technical_contract_pass"] = True
    except BaseException as exc:
        summary.update(technical_contract_pass=False, error=f"{type(exc).__name__}: {exc}",
                       traceback=traceback.format_exc())
    finally:
        if receive is not None:
            receive.close()
        if child is not None and child.pid is not None:
            shutdown.set()
            child.join(8)
            method = "graceful"
            if child.is_alive():
                method = "terminate_owned_child"
                child.terminate()
                child.join(4)
            if child.is_alive():
                method = "kill_owned_child"
                child.kill()
                child.join(4)
            summary["cleanup"] = dict(owned_pid=child.pid, method=method, process_exited=not child.is_alive(),
                                      exitcode=child.exitcode,
                                      gpu_release="owned process exit releases its CUDA context; no other process touched")
            if child.is_alive() or child.exitcode != 0:
                summary["technical_contract_pass"] = False
            if child.is_alive():
                summary["cleanup"]["gpu_release"] = "unverified: owned process still alive"
        else:
            summary["cleanup"] = dict(process_started=False, process_exited=True)
        if (out / "budget.json").exists():
            summary["budget"] = json.loads((out / "budget.json").read_text(encoding="utf-8"))
        if (out / "environment.json").exists():
            environment = json.loads((out / "environment.json").read_text(encoding="utf-8"))
            summary["gpu0_memory"] = {k: v for k, v in environment.items() if k.startswith("gpu_memory_")}
        summary["not_sent_requests"] = sum(r["state"] == "not_sent" for r in summary["requests"])
        save(out / "summary.json", summary)
    print(json.dumps(dict(summary=str(out / "summary.json"), technical_contract_pass=summary["technical_contract_pass"],
                          dispatched_requests=summary["dispatched_requests"], planned_requests=5), ensure_ascii=False))
    return 0 if summary["technical_contract_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
