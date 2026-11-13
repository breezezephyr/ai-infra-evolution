#!/usr/bin/env python3
"""Prepare frozen, replayable exp14 inputs using only stdlib and local macOS TTS.

    python3 -B phase4/exp14/prepare_audio.py --output phase4/exp14/audio

Every segment is synthesized independently with installed Tingting, converted by
afconvert, and trimmed to its first/last active 10 ms RMS window. The fixed
threshold is 120 in signed PCM16 units (about -48.7 dBFS). speech_intervals are
the outer energy envelope of each segment, including any internal quiet windows,
in half-open sample offsets. They are estimates for OFFLINE analysis, NOT human
ground truth or input to online VAD. Regeneration depends on the installed voice;
replay the saved WAVs and verify their SHA-256 for a fixed experiment input.
"""

import argparse
from array import array
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import wave


ROOT = Path(__file__).resolve().parent
SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
WINDOW_SAMPLES = 160
RMS_THRESHOLD = 120
TAIL_SAMPLES = 12800
MAX_SAMPLES = 240000
RATE_WPM = 220
SAY = Path("/usr/bin/say")
AFCONVERT = Path("/usr/bin/afconvert")

ANNOTATION = {
    "method": "per_segment_first_last_window_rms",
    "use": "offline_analysis_only",
    "human_ground_truth": False,
    "provided_to_online_vad": False,
    "units": "samples",
    "interval_convention": "[start,end)",
    "window_samples": WINDOW_SAMPLES,
    "window_ms": 10,
    "rms_threshold_pcm16": RMS_THRESHOLD,
    "rms_threshold_dbfs": -48.725,
    "comparison": ">=",
    "window_origin": "untrimmed segment start; non-overlapping windows",
    "partial_window": "divide energy by actual sample count",
    "interval_scope": "one outer envelope per segment; internal silence is included",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_cases(path=ROOT / "cases.json"):
    """Validate the fixed input set before invoking system tools or writing WAVs."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = document["cases"]
    if len(cases) != 12 or Counter(c["category"] for c in cases) != {
        "short": 6, "pause": 3, "long_request": 3
    }:
        raise ValueError("expected 12 cases: 6 short, 3 pause, 3 long_request")
    seen_ids, seen_texts = set(), set()
    for case in cases:
        case_id, text = case["id"], case["reference_text"]
        segments, pauses = case["segments"], case["pauses_ms"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", case_id):
            raise ValueError("unsafe or empty case id")
        if case_id in seen_ids or text in seen_texts:
            raise ValueError("duplicate case id or reference_text")
        if not segments or any(not isinstance(s, str) or not s.strip() for s in segments):
            raise ValueError(f"{case_id}: empty segment")
        if text != "".join(segments):
            raise ValueError(f"{case_id}: reference_text must include every segment")
        if len(pauses) != len(segments) - 1 or any(
            type(pause) is not int or pause not in (300, 600) for pause in pauses
        ):
            raise ValueError(f"{case_id}: one 300/600 ms pause required per segment boundary")
        if (case["category"] == "pause") != bool(pauses):
            raise ValueError(f"{case_id}: category and segment boundaries disagree")
        if case.get("source") != "self_authored_chinese":
            raise ValueError(f"{case_id}: missing text provenance")
        seen_ids.add(case_id)
        seen_texts.add(text)
    return cases


def read_pcm16(path):
    """Reject conversion failures instead of treating a success exit as audio proof."""
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                wav.getcomptype()) != (1, 2, SAMPLE_RATE, "NONE"):
            raise ValueError(f"{path}: expected mono 16000 Hz PCM16 WAV")
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    if not frames or len(raw) != frames * 2:
        raise ValueError(f"{path}: empty or truncated PCM")
    return raw


def trim_silence(raw):
    """Return PCM and original [start,end) offsets from a declared RMS threshold."""
    if not raw or len(raw) % 2:
        raise ValueError("empty PCM or half PCM16 sample")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    active = []
    for start in range(0, len(samples), WINDOW_SAMPLES):
        window = samples[start:start + WINDOW_SAMPLES]
        # Integer comparison avoids sqrt rounding at the fixed threshold.
        if sum(value * value for value in window) >= RMS_THRESHOLD ** 2 * len(window):
            active.append((start, start + len(window)))
    if not active:
        raise ValueError("silent segment: no window reaches energy threshold")
    start, end = active[0][0], active[-1][1]
    return raw[start * 2:end * 2], start, end


def assemble_case(case, clips):
    """Trim each spoken piece, insert exact zero gaps, then append aligned tail."""
    if len(clips) != len(case["segments"]):
        raise ValueError("one PCM clip required for every segment")
    output = bytearray()
    segments, intervals, pauses = [], [], []
    for index, (text, clip) in enumerate(zip(case["segments"], clips)):
        trimmed, trim_start, trim_end = trim_silence(clip)
        start = len(output) // 2
        output.extend(trimmed)
        end = len(output) // 2
        intervals.append({"start": start, "end": end})
        segments.append({
            "text": text, "source_samples": len(clip) // 2,
            "trim_start": trim_start, "trim_end": trim_end,
            "start": start, "end": end,
        })
        if index < len(case["pauses_ms"]):
            duration_ms = case["pauses_ms"][index]
            gap_samples = duration_ms * SAMPLE_RATE // 1000
            output.extend(bytes(gap_samples * 2))
            pauses.append({"start": end, "end": end + gap_samples,
                           "duration_ms": duration_ms})
    speech_end = len(output) // 2
    total = ((speech_end + TAIL_SAMPLES + FRAME_SAMPLES - 1)
             // FRAME_SAMPLES * FRAME_SAMPLES)
    if total > MAX_SAMPLES:
        raise ValueError(f"{case['id']}: {total} samples exceeds 15 s / {MAX_SAMPLES}; "
                         "input was not truncated")
    output.extend(bytes((total - speech_end) * 2))
    return bytes(output), {
        "samples": total, "duration_seconds": total / SAMPLE_RATE,
        "speech_intervals": intervals, "segments": segments,
        "inserted_pauses": pauses, "tail_silence_samples": total - speech_end,
    }


def run_tool(command):
    """Use local executables only; surface native failures with their diagnostics."""
    try:
        result = subprocess.run([str(part) for part in command], check=True,
                                capture_output=True, text=True, timeout=60)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{command[0]} failed ({error.returncode}): "
                           f"{error.stderr.strip() or error.stdout.strip()}") from error
    return result.stdout.strip()


def probe_source():
    if sys.platform != "darwin" or not SAY.is_file() or not AFCONVERT.is_file():
        raise RuntimeError("local macOS say and afconvert are required; no fallback audio")
    inventory = run_tool([SAY, "-v", "?"])
    voice = next((line for line in inventory.splitlines()
                  if re.match(r"^Tingting\s+zh_CN\s", line)), None)
    if voice is None:
        raise RuntimeError("installed say voices do not include Tingting zh_CN; "
                           "inspect /usr/bin/say -v '?' locally; no download attempted")
    return {
        "engine": "macOS say + afconvert",
        "voice": "Tingting", "language": "zh_CN", "rate_wpm": RATE_WPM,
        "voice_inventory_entry": voice.strip(),
        "macos_version": run_tool(["/usr/bin/sw_vers", "-productVersion"]),
        "macos_build": run_tool(["/usr/bin/sw_vers", "-buildVersion"]),
        "binary_sha256": {"say": sha256(SAY), "afconvert": sha256(AFCONVERT)},
        "script_sha256": sha256(__file__),
        "cases_sha256": sha256(ROOT / "cases.json"),
        "text_source": "self_authored_chinese",
        "synthesis_command": [str(SAY), "-v", "Tingting", "-r", str(RATE_WPM),
                              "-f", "{segment}.txt", "-o", "{segment}.aiff"],
        "conversion_command": [str(AFCONVERT), "-f", "WAVE", "-d", "LEI16@16000",
                               "-c", "1", "{segment}.aiff", "{segment}.wav"],
    }


def synthesize_segment(text, directory, stem):
    text_path = directory / f"{stem}.txt"
    aiff_path = directory / f"{stem}.aiff"
    wav_path = directory / f"{stem}.wav"
    text_path.write_text(text, encoding="utf-8")
    run_tool([SAY, "-v", "Tingting", "-r", str(RATE_WPM),
              "-f", text_path, "-o", aiff_path])
    run_tool([AFCONVERT, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
              aiff_path, wav_path])
    return read_pcm16(wav_path)


def prepare(output):
    cases = load_cases()
    source = probe_source()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": source, "sample_rate": SAMPLE_RATE, "cases": [],
        "format": "mono PCM16LE WAV", "frame_samples": FRAME_SAMPLES,
        "minimum_tail_silence_samples": TAIL_SAMPLES,
        "maximum_samples": MAX_SAMPLES, "annotation": ANNOTATION,
    }
    # Stage everything under --output. A failed synthesis leaves no partial new set.
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=output) as tmp:
        staging = Path(tmp)
        for case in cases:
            clips = [synthesize_segment(text, staging, f"{case['id']}-{index}")
                     for index, text in enumerate(case["segments"])]
            raw, metadata = assemble_case(case, clips)
            filename = f"{case['id']}.wav"
            path = staging / filename
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(raw)
            if read_pcm16(path) != raw:
                raise ValueError(f"{filename}: written PCM does not match prepared samples")
            manifest["cases"].append({
                "id": case["id"], "category": case["category"],
                "reference_text": case["reference_text"], "wav": filename,
                "sample_rate": SAMPLE_RATE, "source": source,
                **metadata, "sha256": sha256(path),
            })
            print(f"{filename}: {metadata['samples']} samples, "
                  f"{metadata['duration_seconds']:.2f} s", flush=True)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for item in manifest["cases"]:
            (staging / item["wav"]).replace(output / item["wav"])
        (staging / "manifest.json").replace(output / "manifest.json")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "audio",
                        help="destination directory for 12 WAVs and manifest.json")
    args = parser.parse_args(argv)
    try:
        manifest = prepare(args.output)
    except (OSError, ValueError, KeyError, RuntimeError, wave.Error,
            subprocess.TimeoutExpired) as error:
        parser.exit(1, f"audio preparation failed: {error}\n")
    print(f"saved {len(manifest['cases'])} WAVs and {args.output / 'manifest.json'}")


if __name__ == "__main__":
    main()
