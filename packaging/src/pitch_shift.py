"""Shift the pitch of a media file with FFmpeg and Rubber Band R3."""

import argparse
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


VIDEO_CODECS = {
    ".mp4": "alac",
    ".m4v": "alac",
    ".mov": "alac",
    ".mkv": "flac",
    ".webm": "libopus",
}
OUTPUT_CODECS = {
    **VIDEO_CODECS,
    ".wav": "pcm_s24le",
    ".aif": "pcm_s24be",
    ".aiff": "pcm_s24be",
    ".flac": "flac",
    ".m4a": "alac",
    ".mp3": "libmp3lame",
    ".ogg": "libopus",
    ".opus": "libopus",
}


@dataclass(frozen=True)
class Media:
    streams: list[dict]
    audio_tracks: list[dict]
    has_video: bool
    format_names: list[str]
    duration_us: int | None

    @property
    def output_codecs(self):
        return VIDEO_CODECS if self.has_video else OUTPUT_CODECS


def find_command(name):
    if hasattr(sys, "_MEIPASS"):
        contents = Path(sys.executable).parent.parent
        paths = [str(contents / "Helpers"), str(contents / "Resources" / "yt-dlp")]
    else:
        # Finder launches apps with a minimal PATH. Search local installs too.
        project_bin = Path(__file__).resolve().parents[2] / ".venv/bin"
        paths = [*os.get_exec_path(), str(Path(sys.prefix) / "bin"),
                 str(project_bin), "/opt/homebrew/bin", "/usr/local/bin"]
    executable = shutil.which(name, path=os.pathsep.join(paths))
    if executable is None:
        raise ValueError(f"必要なコマンドが見つかりません（{name}）")
    return executable


def check_command_status(name, returncode, stderr):
    if returncode:
        detail = stderr.strip()
        message = f"{name} の処理に失敗しました（終了コード {returncode}）。"
        raise ValueError(f"{message}\n{detail}" if detail else message)


def run_command(name, *options, read_stdout=False):
    result = subprocess.run(
        [find_command(name), *options], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if read_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
    )
    check_command_status(name, result.returncode, result.stderr)
    return result.stdout


def run_progress_command(name, *options, on_line, progress_on_stderr=False):
    # Read the progress pipe continuously and keep diagnostics without a second pipe to drain.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as diagnostics:
        with subprocess.Popen(
            [find_command(name), *options], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if progress_on_stderr else subprocess.PIPE,
            stderr=subprocess.PIPE if progress_on_stderr else diagnostics,
            encoding="utf-8", errors="replace",
        ) as process:
            lines = process.stderr if progress_on_stderr else process.stdout
            try:
                for line in lines:
                    handled = on_line(line.strip())
                    if progress_on_stderr and not handled:
                        diagnostics.write(line)
            except BaseException:
                process.kill()
                raise
            returncode = process.wait()
        if returncode:
            diagnostics.seek(0)
            check_command_status(name, returncode, diagnostics.read())


def youtube_video_url(url):
    message = "YouTube の動画を1本指定する URL を入力してください"
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        raise ValueError(message) from None
    host = parsed.netloc.lower()
    video_id = ""
    if parsed.scheme in ("http", "https"):
        if host in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path.removeprefix("/")
        elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [""])[0]
            elif parsed.path.count("/") == 2 and parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
                video_id = parsed.path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError(message)
    return f"https://www.youtube.com/watch?v={video_id}"


def download_youtube(url, folder):
    url = youtube_video_url(url)
    folder = folder.absolute()
    if not folder.is_dir():
        raise ValueError(f"保存先フォルダが見つかりません（{folder}）")
    with tempfile.TemporaryDirectory(prefix=".youtube-", dir=folder) as temporary:
        staging = Path(temporary)
        container = "mp4"
        options = (
            "--ignore-config", "--no-plugin-dirs", "--no-playlist", "--no-cache-dir",
            "--ffmpeg-location", find_command("ffmpeg"), "--js-runtimes", f"deno:{find_command('deno')}",
            "--format", "bv[vcodec^=avc1]+ba[acodec^=mp4a]/b[vcodec^=avc1][acodec^=mp4a]",
            "--merge-output-format", container, "--remux-video", container,
            "--paths", str(staging),
        )
        result = run_command(
            "yt-dlp", *options, "--simulate", "--output", "%(title).120B [%(id)s].%(ext)s",
            "--print", "%(filename)j", "--", url, read_stdout=True,
        )
        invalid_name = "yt-dlp が動画の保存名を特定できません"
        try:
            filename = json.loads(result)
        except json.JSONDecodeError:
            raise ValueError(invalid_name) from None
        if not isinstance(filename, str) or Path(filename).parent != staging:
            raise ValueError(invalid_name)
        output = folder / Path(filename).with_suffix(f".{container}").name
        collision = f"保存先に同名のファイルが既に存在します（{output}）"
        if os.path.lexists(output):
            raise ValueError(collision)

        # Keep the checked destination even if YouTube changes the title during the download.
        run_command("yt-dlp", *options, "--check-formats", "--output", "video.%(ext)s", "--", url)
        source = staging / f"video.{container}"
        if not source.is_file():
            raise ValueError("yt-dlp が取得した動画ファイルを確認できません")
        try:
            os.link(source, output)
        except FileExistsError:
            raise ValueError(collision) from None
        return output


def probe(path, *options):
    result = run_command("ffprobe", "-v", "error", *options, "-of", "json", str(path), read_stdout=True)
    return json.loads(result)


def ffmpeg(*options, on_progress, stage, total, progress_key="out_time_us"):
    flags = ("-nostdin", "-hide_banner", "-loglevel", "error", "-xerror")
    if on_progress is not None:
        on_progress(stage, 0 if total else None)
    if on_progress is None or not total:
        run_command("ffmpeg", *flags, *options)
        return

    last_percent = 0

    def report(line):
        nonlocal last_percent
        key, _, value = line.partition("=")
        if key == progress_key and value.isdecimal():
            percent = min(99, 100 * int(value) // total)
            if percent > last_percent:
                last_percent = percent
                on_progress(stage, percent)

    run_progress_command("ffmpeg", *flags, "-progress", "pipe:1", "-stats_period", "0.25", *options, on_line=report)


def parse_semitones(value):
    try:
        semitones = float(value)
    except ValueError:
        raise ValueError("半音数は有限の数値を指定してください") from None
    if not math.isfinite(semitones):
        raise ValueError("半音数は有限の数値を指定してください")
    return semitones


def duration_us(metadata):
    try:
        duration = Fraction(metadata.get("duration") or "")
    except ValueError:
        return None
    return round(duration * 1_000_000) if duration > 0 else None


def inspect_media(source):
    if not source.is_file():
        raise ValueError(f"入力ファイルが見つかりません（{source}）")
    media = probe(source, "-show_streams", "-show_format")
    streams = media.get("streams", [])
    tracks = [stream for stream in streams if stream["codec_type"] == "audio"]
    if not tracks:
        raise ValueError("入力ファイルに音声トラックがありません")
    has_video = any(
        stream["codec_type"] == "video" and not stream["disposition"].get("attached_pic")
        for stream in streams
    )
    container = media["format"]
    return Media(streams, tracks, has_video, container["format_name"].split(","), duration_us(container))


def pcm_shape(path):
    stream, = probe(path, "-show_streams")["streams"]
    rate = int(stream["sample_rate"])
    samples = stream.get("duration_ts", 0) * Fraction(stream["time_base"]) * rate
    if samples <= 0 or samples.denominator != 1:
        raise ValueError(f"一時音声のサンプル数を確認できません: {path.name}")
    return rate, stream["channels"], int(samples)


def audio_start(source, track):
    # Decode the start, because packet timestamps can include codec priming.
    data = probe(
        source, "-select_streams", str(track["index"]), "-read_intervals", "%+#64",
        "-show_frames", "-show_entries", "frame=best_effort_timestamp",
    )
    frames = data.get("frames", [])
    if not frames or "best_effort_timestamp" not in frames[0]:
        raise ValueError("選択した音声トラックの開始時刻を確認できません")
    return int(frames[0]["best_effort_timestamp"]) * Fraction(track["time_base"])


def write_output(source, processed, output, streams, track, start, codec, *, on_progress, duration):
    index = track["index"]
    args = ["-i", str(source)]
    mapping = ["-map", "1:a:0"]
    output_index = 0
    if start is not None:
        offset = round(start * 1_000_000)
        args = ["-copyts", *args, "-itsoffset", f"{offset}us"]
        mapping = []
        for position, stream in enumerate(streams):
            stream_index = stream["index"]
            if stream_index == index:
                mapping.extend(("-map", "1:a:0"))
                output_index = position
            else:
                mapping.extend(("-map", f"0:{stream_index}"))

    layout = track.get("channel_layout")
    if layout and layout != "unknown":
        args.extend(("-channel_layout", layout))
    args.extend(("-i", str(processed), *mapping, "-map_metadata", "0"))
    args.extend((f"-map_metadata:s:{output_index}", f"0:s:{index}"))
    flags = "+".join(name for name, enabled in track["disposition"].items() if enabled)
    args.extend((f"-disposition:{output_index}", flags or "0"))
    if start is not None:
        args.extend(("-c", "copy", "-avoid_negative_ts", "disabled"))
    args.extend((f"-c:{output_index}", codec))
    if codec == "alac":
        args.extend(("-movie_timescale", track["sample_rate"]))
    if codec == "libopus":
        args.extend((f"-b:{output_index}", f"{min(96 * track['channels'], 512)}k"))
    if codec == "libmp3lame":
        args.extend((f"-q:{output_index}", "2"))
    if output.suffix.lower() == ".wav":
        args.extend(("-rf64", "auto"))
    if output.suffix.lower() == ".m4v":
        args.extend(("-f", "mp4"))
    ffmpeg(*args, str(output), on_progress=on_progress, stage="出力ファイルを保存中", total=duration)


def render_pitch(original, processed, semitones, preserve_formants, *, on_progress):
    options = ["--fine", "--time", "1", "--pitch", str(semitones)]
    if preserve_formants:
        options.append("--formant")
    # The offline engine compensates its own processing delay.
    if on_progress is None:
        run_command("rubberband", "--quiet", *options, str(original), str(processed))
        return

    stages = {"Pass 1": "音声を解析中", "Pass 2": "ピッチを変換中"}
    stage = None
    last_percent = 0
    on_progress(stages["Pass 1"], None)

    def report(line):
        nonlocal stage, last_percent
        next_stage = stages.get(line.partition(":")[0])
        if next_stage is not None:
            stage = next_stage
            last_percent = 0
            on_progress(stage, 0)
            return True
        match = re.fullmatch(r"(\d{1,3})%", line)
        if match and stage is not None:
            percent = min(99, int(match[1]))
            if percent > last_percent:
                last_percent = percent
                on_progress(stage, percent)
            return True
        return False

    run_progress_command("rubberband", *options, str(original), str(processed), on_line=report, progress_on_stderr=True)


def check_destination(source, output, replace_existing):
    if replace_existing is None:
        if os.path.lexists(output):
            raise ValueError(f"出力先が既に存在します（{output}）")
        return

    try:
        actual = output.lstat()
    except FileNotFoundError:
        raise ValueError(f"上書きを確認した出力先が移動または削除されました（{output}）") from None
    if not stat.S_ISREG(actual.st_mode):
        raise ValueError(f"通常のファイルだけを上書きできます（{output}）")
    if os.path.samestat(source.stat(), actual):
        raise ValueError(f"入力ファイルは上書きできません（{output}）")
    if (not os.path.samestat(actual, replace_existing)
            or actual.st_mtime_ns != replace_existing.st_mtime_ns
            or actual.st_ctime_ns != replace_existing.st_ctime_ns
            or actual.st_size != replace_existing.st_size):
        raise ValueError(f"上書きを確認した出力先が変更されました（{output}）")


def decoded_pcm_bytes(track, duration, samples):
    if samples is None:
        try:
            sample_rate = int(track.get("sample_rate", ""))
        except (TypeError, ValueError):
            return None
        if not duration:
            return None
        samples = round(Fraction(duration * sample_rate, 1_000_000))
    channels = track.get("channels") or 0
    return samples * channels * 4


def shift(source, output, semitones, audio_track, preserve_formants, *, replace_existing=None, on_progress=None):
    source, output = source.absolute(), output.absolute()
    semitones = parse_semitones(semitones)
    check_destination(source, output, replace_existing)
    if not output.parent.is_dir():
        raise ValueError(f"出力先フォルダが見つかりません（{output.parent}）")

    media = inspect_media(source)
    if not 0 <= audio_track < len(media.audio_tracks):
        raise ValueError(f"音声トラック番号は 0〜{len(media.audio_tracks) - 1} を指定してください")
    track = media.audio_tracks[audio_track]
    codecs = media.output_codecs
    codec = codecs.get(output.suffix.lower())
    if codec is None:
        raise ValueError(f"出力形式は {', '.join(codecs)} から選んでください")

    # MOV/MP4 edit lists can end inside the last decoded AAC frame.
    has_edit_length = (
        "mov" in media.format_names and "duration_ts" in track and "start_pts" in track
    )
    start = audio_start(source, track) if media.has_video or has_edit_length else None
    filters = []
    samples = None
    if start is not None:
        # Keep gaps in the playback timeline by inserting silence, without stretching samples.
        filters.append("aresample=async=1:min_hard_comp=0.002")
    if has_edit_length:
        end = (track["start_pts"] + track["duration_ts"]) * Fraction(track["time_base"])
        samples = round((end - start) * int(track["sample_rate"]))
        if samples <= 0:
            raise ValueError("選択した音声トラックの再生範囲を確認できません")
        filters.extend((f"apad=whole_len={samples}", f"atrim=end_sample={samples}"))

    with tempfile.TemporaryDirectory(prefix=".pitch-shift-", dir=output.parent) as directory:
        work = Path(directory)
        original = work / "original.wav"
        decode = ["-i", str(source), "-map", f"0:{track['index']}"]
        if filters:
            decode = ["-copyts", *decode, "-af", ",".join(filters)]
        decode_bytes = None
        if on_progress is not None:
            track_duration = duration_us(track)
            if not track_duration and len(media.streams) == 1:
                track_duration = media.duration_us
            # The PCM byte count is independent of timestamps retained by -copyts.
            decode_bytes = decoded_pcm_bytes(track, track_duration, samples)
        ffmpeg(
            *decode, "-c:a", "pcm_f32le", "-rf64", "auto", str(original),
            on_progress=on_progress, stage="音声を抽出中", total=decode_bytes, progress_key="total_size",
        )
        expected_shape = pcm_shape(original)
        processed = original
        if semitones:
            processed = work / "shifted.wav"
            render_pitch(original, processed, semitones, preserve_formants, on_progress=on_progress)
            if pcm_shape(processed) != expected_shape:
                raise ValueError("変換後のサンプルレート、チャンネル数、またはサンプル数が入力と一致しません")

        staged = work / f"result{output.suffix.lower()}"
        rate, _, sample_count = expected_shape
        output_duration = media.duration_us if media.has_video else round(Fraction(sample_count * 1_000_000, rate))
        write_output(
            source, processed, staged, media.streams, track, start if media.has_video else None, codec,
            on_progress=on_progress, duration=output_duration,
        )
        if replace_existing is None:
            # An output created during conversion must be left alone.
            os.link(staged, output)
        else:
            check_destination(source, output, replace_existing)
            os.replace(staged, output)


def main():
    parser = argparse.ArgumentParser(description="再生速度と尺を保ったまま音声のピッチを変えます。")
    parser.add_argument("input", help="入力の動画・音声ファイル、または YouTube 動画の URL")
    parser.add_argument("output", type=Path, help="出力ファイル（既存ファイルは上書きしません）")
    parser.add_argument("-p", "--semitones", required=True, help="半音単位の変化量（例: 3、-2.5）")
    parser.add_argument("--audio-track", type=int, default=0, help="変換する音声トラック番号（0始まり）")
    parser.add_argument("-F", "--preserve-formants", action="store_true", help="元の声質を保つフォルマント保持")
    args = parser.parse_args()

    try:
        if args.input.strip().lower().startswith(("http://", "https://")):
            parse_semitones(args.semitones)
            check_destination(None, args.output, None)
            if not args.output.parent.is_dir():
                raise ValueError(f"出力先フォルダが見つかりません（{args.output.parent}）")
            with tempfile.TemporaryDirectory(prefix="youtube-") as temporary:
                source = download_youtube(args.input, Path(temporary))
                shift(source, args.output, args.semitones, args.audio_track, args.preserve_formants)
        else:
            shift(Path(args.input), args.output, args.semitones, args.audio_track, args.preserve_formants)
    except (OSError, ValueError) as error:
        parser.exit(1, f"エラー: {error}\n")


if __name__ == "__main__":
    main()
