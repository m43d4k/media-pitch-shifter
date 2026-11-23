import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import pitch_shift


SCRIPT = Path(pitch_shift.__file__).resolve()
SAMPLE_RATE = 48_000
SAMPLE_COUNT = SAMPLE_RATE + 137


class PitchShiftTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.audio = self.folder / "original tone.wav"
        with wave.open(str(self.audio), "wb") as wav:
            wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", ""))
            wav.writeframes(b"".join(
                struct.pack("<h", round(10_000 * math.sin(2 * math.pi * 440 * n / SAMPLE_RATE)))
                for n in range(SAMPLE_COUNT)
            ))

    def shift(self, source, output, *options):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(source), str(output), *options],
            capture_output=True, text=True,
        )

    def run_tool(self, *args):
        return subprocess.check_output(args, stderr=subprocess.PIPE)

    def streams(self, path):
        return json.loads(self.run_tool(
            "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)
        ))["streams"]

    def stream_hash(self, path, stream):
        return self.run_tool(
            "ffmpeg", "-v", "error", "-i", str(path), "-map", stream,
            "-c", "copy", "-f", "streamhash", "-",
        )

    def test_wav_pitch_changes_with_exact_input_length(self):
        output = self.folder / "pitched.wav"
        result = self.shift(self.audio, output, "--semitones", "-5.5", "--preserve-formants")
        self.assertEqual(result.returncode, 0, result.stderr)
        audio, = self.streams(output)
        self.assertEqual(int(audio["sample_rate"]), SAMPLE_RATE)
        self.assertEqual(audio["duration_ts"], SAMPLE_COUNT)

        pcm = self.run_tool("ffmpeg", "-v", "error", "-i", str(output), "-f", "s16le", "-")
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        middle = samples[SAMPLE_RATE // 4:3 * SAMPLE_RATE // 4]
        crossings = sum(a <= 0 < b for a, b in zip(middle, middle[1:]))
        self.assertAlmostEqual(2 * crossings, 440 * 2 ** (-5.5 / 12), delta=4)

    def test_wav_positive_fractional_pitch(self):
        output = self.folder / "raised.wav"
        result = self.shift(self.audio, output, "-p", "3.5")
        self.assertEqual(result.returncode, 0, result.stderr)
        audio, = self.streams(output)
        self.assertEqual(int(audio["sample_rate"]), SAMPLE_RATE)
        self.assertEqual(audio["channels"], 1)
        self.assertEqual(audio["duration_ts"], SAMPLE_COUNT)
        pcm = self.run_tool("ffmpeg", "-v", "error", "-i", str(output), "-f", "s16le", "-")
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        middle = samples[SAMPLE_RATE // 4:3 * SAMPLE_RATE // 4]
        crossings = sum(a <= 0 < b for a, b in zip(middle, middle[1:]))
        self.assertAlmostEqual(2 * crossings, 440 * 2 ** (3.5 / 12), delta=4)

    def test_wav_reports_measured_progress_for_each_stage(self):
        output = self.folder / "pitched.wav"
        updates = {}

        def report(stage, percent):
            self.assertFalse(output.exists())
            percentages = updates.setdefault(stage, [])
            if percent is not None:
                percentages.append(percent)

        pitch_shift.shift(self.audio, output, 2.5, 0, True, on_progress=report)

        self.assertTrue(output.is_file())
        self.assertEqual(list(updates), [
            "音声を抽出中", "音声を解析中", "ピッチを変換中", "出力ファイルを保存中",
        ])
        for percentages in updates.values():
            self.assertEqual(percentages, sorted(set(percentages)))
            self.assertEqual(percentages[0], 0)
            self.assertTrue(any(0 < percent < 100 for percent in percentages))
            self.assertLess(percentages[-1], 100)

    def test_zero_semitones_reports_extraction_and_saving_only(self):
        output = self.folder / "unchanged.wav"
        stages = set()

        def report(stage, _percent):
            stages.add(stage)

        pitch_shift.shift(self.audio, output, 0, 0, False, on_progress=report)

        self.assertEqual(stages, {"音声を抽出中", "出力ファイルを保存中"})

    def test_video_keeps_delayed_audio_sync_and_other_streams(self):
        source = self.folder / "original.mkv"
        output = self.folder / "pitched.mkv"
        self.run_tool(
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24:d=2",
            "-i", str(self.audio), "-itsoffset", "0.375", "-i", str(self.audio),
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "pcm_s16le",
            "-metadata:s:a:1", "language=jpn", "-disposition:a:1", "default", str(source),
        )
        result = self.shift(source, output, "--semitones", "3", "--audio-track", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        original_video, _, original_audio = self.streams(source)
        video, _, audio = self.streams(output)
        self.assertEqual(video["start_time"], original_video["start_time"])
        self.assertEqual(audio["start_time"], original_audio["start_time"])
        self.assertEqual(audio["disposition"]["default"], 1)
        self.assertEqual(audio["tags"]["language"], "jpn")
        self.assertEqual(self.stream_hash(source, "0:v:0"), self.stream_hash(output, "0:v:0"))
        self.assertEqual(self.stream_hash(source, "0:a:0"), self.stream_hash(output, "0:a:0"))
        pcm = self.run_tool(
            "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:1", "-f", "s16le", "-",
        )
        self.assertEqual(len(pcm) // 2, SAMPLE_COUNT)

    def test_existing_output_is_preserved(self):
        output = self.folder / "existing.wav"
        output.write_bytes(b"keep this")
        result = self.shift(self.audio, output, "--semitones", "3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(output), result.stderr)
        self.assertEqual(output.read_bytes(), b"keep this")

    def test_m4a_preserves_playable_duration(self):
        source = self.folder / "original.m4a"
        output = self.folder / "pitched.m4a"
        self.run_tool("ffmpeg", "-v", "error", "-i", str(self.audio), "-c:a", "aac", str(source))
        result = self.shift(source, output, "-p", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        original, = self.streams(source)
        processed, = self.streams(output)
        self.assertEqual(processed["duration_ts"], original["duration_ts"])

    def test_mp4_keeps_aac_track_start_time(self):
        source = self.folder / "original.mp4"
        self.run_tool(
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24:d=2",
            "-itsoffset", "0.375", "-i", str(self.audio), "-c:v", "mpeg4", "-c:a", "aac",
            str(source),
        )
        _, original = self.streams(source)
        original_video = self.stream_hash(source, "0:v:0")
        for suffix in (".mp4", ".m4v"):
            with self.subTest(suffix=suffix):
                output = self.folder / f"pitched{suffix}"
                result = self.shift(source, output, "-p", "3", "-F")
                self.assertEqual(result.returncode, 0, result.stderr)
                _, processed = self.streams(output)
                self.assertEqual(processed["start_pts"], original["start_pts"])
                self.assertLessEqual(abs(processed["duration_ts"] - original["duration_ts"]), 1)
                self.assertEqual(self.stream_hash(output, "0:v:0"), original_video)

    def test_confirmed_overwrite_is_published_only_after_success(self):
        output = self.folder / "existing.wav"
        output.write_bytes(b"keep this until conversion succeeds")
        confirmed = output.lstat()
        with self.assertRaises(ValueError):
            pitch_shift.shift(self.audio, output, 0, 1, False, replace_existing=confirmed)
        self.assertEqual(output.read_bytes(), b"keep this until conversion succeeds")

        pitch_shift.shift(self.audio, output, 0, 0, False, replace_existing=confirmed)
        audio, = self.streams(output)
        self.assertEqual(audio["codec_name"], "pcm_s24le")
        self.assertEqual(audio["duration_ts"], SAMPLE_COUNT)

    def test_overwrite_cannot_replace_input_alias(self):
        output = self.folder / "alias.wav"
        output.hardlink_to(self.audio)
        original = self.audio.read_bytes()
        with self.assertRaisesRegex(ValueError, "入力ファイル"):
            pitch_shift.shift(self.audio, output, 0, 0, False, replace_existing=output.lstat())
        self.assertEqual(self.audio.read_bytes(), original)

    def test_video_keeps_an_internal_audio_gap(self):
        source = self.folder / "gap.mkv"
        output = self.folder / "pitched.mkv"
        self.run_tool(
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24:d=2",
            "-i", str(self.audio), "-af", r"asetpts=PTS+if(gte(PTS\,24000)\,12000\,0)",
            "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(source),
        )
        result = self.shift(source, output, "-p", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        pcm = self.run_tool(
            "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:0", "-f", "s16le", "-",
        )
        self.assertAlmostEqual(len(pcm) // 2, SAMPLE_COUNT + 12_000, delta=SAMPLE_RATE // 1000)
        center = struct.unpack_from("<480h", pcm, 30_000 * 2)
        self.assertLess(max(abs(sample) for sample in center), 100)


if __name__ == "__main__":
    unittest.main()
