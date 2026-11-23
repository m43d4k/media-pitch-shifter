import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pitch_shift


VIDEO_ID = "BaW_jenozKc"
WATCH_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
FILENAME = f"試聴用 [{VIDEO_ID}].mp4"


class YouTubeTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.enterContext(patch.object(pitch_shift, "find_command", side_effect=lambda name: f"/mock/bin/{name}"))

    def simulate_download(self, _command, *options, **_kwargs):
        self.assertEqual(options[-1], WATCH_URL)
        staging = Path(options[options.index("--paths") + 1])
        extension = options[options.index("--merge-output-format") + 1]
        if "--simulate" in options:
            return json.dumps(str(staging / Path(FILENAME).with_suffix(f".{extension}")))
        (staging / f"video.{extension}").write_bytes(b"downloaded media")

    def test_downloads_short_link_and_saves_the_finished_video(self):
        with patch.object(pitch_shift, "run_command", side_effect=self.simulate_download):
            path = pitch_shift.download_youtube(f"https://youtu.be/{VIDEO_ID}?si=share", self.folder)
        self.assertEqual(path, self.folder / FILENAME)
        self.assertEqual(path.read_bytes(), b"downloaded media")
        self.assertEqual(list(self.folder.iterdir()), [path])

    def test_reports_separate_transfers_and_mp4_creation_before_saving(self):
        output = self.folder / FILENAME
        updates = []

        def report(stage, percent):
            self.assertFalse(output.exists())
            updates.append((stage, percent))

        def stream_download(command, *options, on_line):
            self.assertIn("--check-formats", options)
            for line in (
                "[info] Testing format 137",
                "media-pitch-download downloading avc1.640028 none 30 100",
                "media-pitch-download downloading avc1.640028 none 30 100",
                "media-pitch-download finished avc1.640028 none 100 100",
                "media-pitch-download downloading none mp4a.40.2 10 NA",
                "media-pitch-download downloading none mp4a.40.2 20 80",
                "media-pitch-postprocess Merger started",
                "media-pitch-postprocess VideoRemuxer started",
                "media-pitch-postprocess MoveFiles finished",
            ):
                on_line(line)
            self.simulate_download(command, *options)

        with (
            patch.object(pitch_shift, "run_command", side_effect=self.simulate_download),
            patch.object(pitch_shift, "run_progress_command", side_effect=stream_download),
        ):
            self.assertEqual(pitch_shift.download_youtube(WATCH_URL, self.folder, on_progress=report), output)

        self.assertEqual(output.read_bytes(), b"downloaded media")
        self.assertEqual(updates, [
            ("映像をダウンロード中", 30), ("映像をダウンロード中", 99),
            ("音声をダウンロード中", None), ("音声をダウンロード中", 25), ("MP4を作成中", None),
        ])

    def test_refuses_non_video_urls(self):
        urls = (
            "https://youtube.com/playlist?list=PLexample",
            f"https://youtube.com.example.org/watch?v={VIDEO_ID}",
            f"https://www.youtube.com/watch?v={VIDEO_ID}/extra",
        )
        with patch.object(pitch_shift, "run_command") as run_command:
            for url in urls:
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, "YouTube"):
                    pitch_shift.download_youtube(url, self.folder)
            run_command.assert_not_called()

    def test_existing_download_is_detected_before_media_transfer(self):
        output = self.folder / FILENAME
        output.write_bytes(b"existing media")
        with patch.object(pitch_shift, "run_command", side_effect=self.simulate_download) as run:
            with self.assertRaisesRegex(ValueError, "既に存在"):
                pitch_shift.download_youtube(WATCH_URL, self.folder)
        run.assert_called_once()
        self.assertIn("--simulate", run.call_args.args)
        self.assertNotIn("--check-formats", run.call_args.args)
        self.assertEqual(output.read_bytes(), b"existing media")
        self.assertEqual(list(self.folder.iterdir()), [output])

    def test_file_created_during_media_transfer_is_preserved(self):
        output = self.folder / FILENAME

        def download_with_collision(command, *options, **kwargs):
            if "--simulate" not in options:
                output.write_bytes(b"existing media")
            return self.simulate_download(command, *options, **kwargs)

        with patch.object(pitch_shift, "run_command", side_effect=download_with_collision):
            with self.assertRaisesRegex(ValueError, "既に存在"):
                pitch_shift.download_youtube(WATCH_URL, self.folder)
        self.assertEqual(output.read_bytes(), b"existing media")
        self.assertEqual(list(self.folder.iterdir()), [output])

    def test_failed_download_cleans_up_partial_file(self):
        def fail_download(command, *options, **kwargs):
            if "--simulate" in options:
                return self.simulate_download(command, *options, **kwargs)
            staging = Path(options[options.index("--paths") + 1])
            (staging / "incomplete.part").touch()
            raise ValueError("取得に失敗")

        with patch.object(pitch_shift, "run_command", side_effect=fail_download):
            with self.assertRaisesRegex(ValueError, "取得に失敗"):
                pitch_shift.download_youtube(WATCH_URL, self.folder)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_cli_passes_download_to_conversion_and_cleans_up(self):
        output = self.folder / "shifted.mkv"
        source = None

        def check_conversion(path, destination, semitones, audio_track, preserve_formants):
            nonlocal source
            source = path
            self.assertEqual(path.read_bytes(), b"downloaded media")
            self.assertEqual((destination, semitones, audio_track, preserve_formants), (output, "-3", 0, True))

        with (
            patch("sys.argv", ["pitch_shift.py", WATCH_URL, str(output), "-p", "-3", "-F"]),
            patch.object(pitch_shift, "run_command", side_effect=self.simulate_download),
            patch.object(pitch_shift, "shift", side_effect=check_conversion) as shift,
        ):
            pitch_shift.main()
        shift.assert_called_once()
        self.assertFalse(source.exists())
