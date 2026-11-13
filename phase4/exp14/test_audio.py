"""Offline input checks. Run: python3 -B -m unittest discover -s phase4/exp14 -v."""

import array
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parent
AUDIO = ROOT / "audio"
sys.dont_write_bytecode = True


def pcm(values):
    return struct.pack(f"<{len(values)}h", *values)


class AudioTests(unittest.TestCase):
    def preparer(self):
        path = ROOT / "prepare_audio.py"
        self.assertTrue(path.is_file(), "可重放音频生成功能尚未实现")
        spec = importlib.util.spec_from_file_location("prepare_audio", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def definitions(self):
        path = ROOT / "cases.json"
        self.assertTrue(path.is_file(), "缺少十二条自写中文样本")
        return json.loads(path.read_text(encoding="utf-8"))

    def manifest(self):
        path = AUDIO / "manifest.json"
        self.assertTrue(path.is_file(), "尚未生成真实 Tingting 音频及 manifest")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_trim_uses_energy_instead_of_nonzero_samples(self):
        module = self.preparer()
        raw = pcm([0] * 320 + [60, -60] * 80 + [1000, -1000] * 160
                  + [60, -60] * 80 + [0] * 160)
        trimmed, start, end = module.trim_silence(raw)
        self.assertEqual((start, end), (480, 800))
        self.assertEqual(trimmed, pcm([1000, -1000] * 160))

    def test_threshold_equality_and_partial_last_window(self):
        module = self.preparer()
        with self.assertRaisesRegex(ValueError, "energy|silent"):
            module.trim_silence(pcm([119] * 160))
        self.assertEqual(module.trim_silence(pcm([120] * 161)),
                         (pcm([120] * 161), 0, 161))

    def test_silence_empty_and_half_samples_are_rejected(self):
        module = self.preparer()
        for raw in (b"", b"\x00", pcm([0] * 1600)):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                module.trim_silence(raw)

    def test_exact_pause_insertion_and_all_segment_boundaries(self):
        module = self.preparer()
        case = {"id": "pause_test", "category": "pause",
                "reference_text": "先听这里，再等一下，最后继续。",
                "segments": ["先听这里，", "再等一下，", "最后继续。"],
                "pauses_ms": [300, 600]}
        clip = pcm([0] * 160 + [1000, -1000] * 160 + [0] * 160)
        output, meta = module.assemble_case(case, [clip, clip, clip])
        self.assertEqual(meta["speech_intervals"], [
            {"start": 0, "end": 320}, {"start": 5120, "end": 5440},
            {"start": 15040, "end": 15360}])
        self.assertEqual(meta["inserted_pauses"], [
            {"start": 320, "end": 5120, "duration_ms": 300},
            {"start": 5440, "end": 15040, "duration_ms": 600}])
        expected = (pcm([1000, -1000] * 160) + bytes(4800 * 2)
                    + pcm([1000, -1000] * 160) + bytes(9600 * 2)
                    + pcm([1000, -1000] * 160) + bytes(12800 * 2))
        self.assertEqual(output, expected)
        self.assertEqual(meta["samples"], 28160)
        for segment in meta["segments"]:
            self.assertEqual((segment["trim_start"], segment["trim_end"]),
                             (160, 480))
            self.assertEqual(segment["source_samples"], 640)

    def test_tail_padding_rounds_up_to_twenty_ms(self):
        module = self.preparer()
        case = {"id": "align", "category": "short", "reference_text": "你好。",
                "segments": ["你好。"], "pauses_ms": []}
        output, meta = module.assemble_case(case, [pcm([1000] * 161)])
        self.assertEqual(meta["samples"], 13120)
        self.assertEqual(meta["tail_silence_samples"], 12959)
        self.assertEqual(meta["speech_intervals"], [{"start": 0, "end": 161}])
        self.assertEqual(output[322:], bytes(12959 * 2))

    def test_fifteen_second_limit_includes_tail_and_never_truncates(self):
        module = self.preparer()
        case = {"id": "limit", "category": "short", "reference_text": "继续。",
                "segments": ["继续。"], "pauses_ms": []}
        output, meta = module.assemble_case(case, [pcm([1000] * 227200)])
        self.assertEqual((len(output), meta["samples"]), (480000, 240000))
        with self.assertRaisesRegex(ValueError, "15|240000"):
            module.assemble_case(case, [pcm([1000] * 227201)])

    def test_segment_count_mismatch_is_rejected(self):
        module = self.preparer()
        case = {"id": "bad", "category": "short", "reference_text": "你好。",
                "segments": ["你好。"], "pauses_ms": []}
        with self.assertRaises(ValueError):
            module.assemble_case(case, [])

    def test_twelve_authored_texts_have_six_three_three_distribution(self):
        cases = self.definitions()["cases"]
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({case["id"] for case in cases}), 12)
        self.assertEqual(len({case["reference_text"] for case in cases}), 12)
        self.assertEqual({category: sum(c["category"] == category for c in cases)
                          for category in ("short", "pause", "long_request")},
                         {"short": 6, "pause": 3, "long_request": 3})
        self.assertGreater(len({len(c["reference_text"]) for c in cases
                                if c["category"] == "short"}), 3)
        for case in cases:
            self.assertEqual(case["reference_text"], "".join(case["segments"]))
            self.assertTrue(any("\u4e00" <= c <= "\u9fff"
                                for c in case["reference_text"]))
            self.assertEqual(len(case["pauses_ms"]), len(case["segments"]) - 1)
            self.assertEqual(case["source"], "self_authored_chinese")
            if case["category"] != "pause":
                self.assertEqual(len(case["segments"]), 1)
        pauses = [p for c in cases for p in c["pauses_ms"]]
        self.assertEqual(set(pauses), {300, 600})

    def test_case_loader_rejects_unsafe_or_inconsistent_definitions(self):
        module = self.preparer()
        document = self.definitions()
        self.assertEqual(module.load_cases(ROOT / "cases.json"), document["cases"])
        AUDIO.mkdir(exist_ok=True)
        for field, value in (("id", "../escape"), ("id", ""),
                             ("reference_text", "漏掉了后半句"),
                             ("pauses_ms", [300]), ("segments", [""])):
            with self.subTest(field=field), tempfile.TemporaryDirectory(dir=AUDIO) as tmp:
                changed = json.loads(json.dumps(document))
                changed["cases"][0][field] = value
                path = Path(tmp) / "cases.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    module.load_cases(path)

    def test_pcm_reader_rejects_stereo_eight_bit_and_wrong_rate(self):
        module = self.preparer()
        AUDIO.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=AUDIO) as tmp:
            for channels, width, rate in ((2, 2, 16000), (1, 1, 16000), (1, 2, 8000)):
                path = Path(tmp) / "bad.wav"
                with wave.open(str(path), "wb") as wav:
                    wav.setparams((channels, width, rate, 0, "NONE", "not compressed"))
                    wav.writeframes(bytes(320 * width * channels))
                with self.subTest(format=(channels, width, rate)), self.assertRaises(ValueError):
                    module.read_pcm16(path)

    def test_cli_documents_output_option(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "prepare_audio.py"),
                                 "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--output", result.stdout)

    def test_generated_manifest_preserves_sources_and_full_text(self):
        manifest = self.manifest()
        definitions = {c["id"]: c for c in self.definitions()["cases"]}
        self.assertEqual(manifest["sample_rate"], 16000)
        self.assertEqual(len(manifest["cases"]), 12)
        self.assertEqual({c["id"] for c in manifest["cases"]}, set(definitions))
        source = manifest["source"]
        self.assertEqual(source["voice"], "Tingting")
        self.assertEqual(source["language"], "zh_CN")
        self.assertEqual(source["engine"], "macOS say + afconvert")
        self.assertTrue(source["macos_version"])
        self.assertTrue(source["macos_build"])
        for key, path in (("script_sha256", ROOT / "prepare_audio.py"),
                          ("cases_sha256", ROOT / "cases.json")):
            self.assertEqual(source[key], hashlib.sha256(path.read_bytes()).hexdigest())
        for item in manifest["cases"]:
            original = definitions[item["id"]]
            self.assertEqual(item["reference_text"], original["reference_text"])
            self.assertEqual(item["category"], original["category"])
            self.assertEqual(item["source"], source)
            self.assertEqual([s["text"] for s in item["segments"]], original["segments"])

    def test_generated_files_hash_format_duration_and_relative_paths(self):
        manifest = self.manifest()
        expected = {"manifest.json"}
        for item in manifest["cases"]:
            with self.subTest(id=item["id"]):
                name = item["wav"]
                self.assertEqual(name, Path(name).name)
                self.assertFalse(Path(name).is_absolute())
                self.assertEqual(name, item["id"] + ".wav")
                expected.add(name)
                path = AUDIO / name
                self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual((wav.getnchannels(), wav.getsampwidth(),
                                      wav.getframerate(), wav.getcomptype()),
                                     (1, 2, 16000, "NONE"))
                    self.assertEqual(wav.getnframes(), item["samples"])
                    raw = wav.readframes(wav.getnframes() + 1)
                self.assertEqual(len(raw), item["samples"] * 2)
                self.assertEqual(item["sample_rate"], 16000)
                self.assertEqual(item["samples"] % 320, 0)
                self.assertLessEqual(item["samples"], 240000)
                self.assertGreater(item["samples"], 12800)
        self.assertEqual({p.name for p in AUDIO.iterdir()}, expected)

    def test_generated_boundaries_are_declared_energy_estimates(self):
        manifest = self.manifest()
        policy = manifest["annotation"]
        self.assertEqual(policy["use"], "offline_analysis_only")
        self.assertFalse(policy["human_ground_truth"])
        self.assertEqual(policy["units"], "samples")
        self.assertEqual(policy["interval_convention"], "[start,end)")
        self.assertEqual(policy["window_samples"], 160)
        self.assertEqual(policy["rms_threshold_pcm16"], 120)
        for item in manifest["cases"]:
            with wave.open(str(AUDIO / item["wav"]), "rb") as wav:
                raw = wav.readframes(wav.getnframes())
            intervals = item["speech_intervals"]
            self.assertEqual(intervals, [{"start": s["start"], "end": s["end"]}
                                         for s in item["segments"]])
            self.assertEqual(intervals[0]["start"], 0)
            previous_end = 0
            for segment in item["segments"]:
                start, end = segment["start"], segment["end"]
                self.assertGreaterEqual(start, previous_end)
                self.assertGreater(end, start)
                self.assertLessEqual(end, item["samples"])
                self.assertEqual(end - start, segment["trim_end"] - segment["trim_start"])
                self.assertLessEqual(segment["trim_end"], segment["source_samples"])
                samples = [v[0] for v in struct.iter_unpack("<h", raw[start * 2:end * 2])]
                active = []
                for offset in range(0, len(samples), 160):
                    window = samples[offset:offset + 160]
                    if sum(v * v for v in window) >= 120 ** 2 * len(window):
                        active.append((offset, offset + len(window)))
                self.assertTrue(active)
                self.assertEqual((active[0][0], active[-1][1]), (0, end - start))
                previous_end = end

    def test_generated_pauses_and_tail_are_exact_zero_samples(self):
        manifest = self.manifest()
        definitions = {c["id"]: c for c in self.definitions()["cases"]}
        for item in manifest["cases"]:
            with self.subTest(id=item["id"]):
                with wave.open(str(AUDIO / item["wav"]), "rb") as wav:
                    raw = wav.readframes(wav.getnframes())
                pauses = item["inserted_pauses"]
                self.assertEqual([p["duration_ms"] for p in pauses],
                                 definitions[item["id"]]["pauses_ms"])
                for index, pause in enumerate(pauses):
                    start, end = pause["start"], pause["end"]
                    self.assertEqual(end - start, pause["duration_ms"] * 16)
                    self.assertEqual(raw[start * 2:end * 2], bytes((end - start) * 2))
                    self.assertEqual(start, item["speech_intervals"][index]["end"])
                    self.assertEqual(end, item["speech_intervals"][index + 1]["start"])
                speech_end = item["speech_intervals"][-1]["end"]
                tail = item["samples"] - speech_end
                self.assertEqual(item["tail_silence_samples"], tail)
                self.assertGreaterEqual(tail, 12800)
                self.assertLess(tail, 13120)
                self.assertEqual(raw[speech_end * 2:], bytes(tail * 2))


if __name__ == "__main__":
    unittest.main()
