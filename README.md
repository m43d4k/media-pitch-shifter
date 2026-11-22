# media-pitch-shifter

動画・音声のピッチを、再生速度と長さを変えずに変更する macOS 用ツール。ローカルファイルと YouTube 動画に対応。

## 使い方

### GUI

1. 「ファイル」タブに動画・音声をドロップするか、「YouTube」タブで URL と保存先を指定してダウンロードする。
2. 「Pitch (st)」に半音数を入力する（例：`-2.5`）。フォルマント保持や音声トラックも設定できる。
3. 「変換」を押す。結果は元ファイルと同じフォルダに保存される（例：`song.mp4` → `song_shift.mp4`）。

### CLI

```sh
# ローカルファイル
uv run pitch_shift.py input.mp4 output.mp4 -p -2.5 --audio-track 0 -F

# YouTube
uv run pitch_shift.py "https://www.youtube.com/watch?v=VIDEO_ID" output.mp4 -p -2.5 -F
```

- `-p`：変更する半音数
- `--audio-track`：音声トラック番号（0 始まり、既定は 0）
- `-F`：フォルマント保持

出力には既存のファイル名を指定できない。

## セットアップ

必要環境：macOS、`uv`、FFmpeg（`ffmpeg`・`ffprobe`）、Deno 2.3 以降。

### 依存ライブラリのインストール

```sh
uv sync
```

### Rubber Band のインストール

公式配布から Rubber Band 4.0.0 の macOS 用 CLI を取得し、`.venv/bin/rubberband` に配置する。[Rubber Band 公式配布ページ](https://breakfastquay.com/rubberband/)

```sh
# ダウンロード・展開
tmp=$(mktemp -d)
curl -fsSL https://breakfastquay.com/files/releases/rubberband-4.0.0-gpl-executable-macos.tar.bz2 -o "$tmp/rubberband.tar.bz2"
tar -xjf "$tmp/rubberband.tar.bz2" -C "$tmp"

# インストール・後片付け
install -m 755 "$tmp/rubberband-4.0.0-gpl-executable-macos/rubberband" .venv/bin/rubberband
rm -rf "$tmp"
```

### アプリ化

```sh
uv run python setup.py py2app -A
```

出力先：`dist/Media Pitch Shifter.app`

## 関連ドキュメント

- [仕様書](SPEC.md)：対応形式、保存・上書き、音声処理
- [作業ルール](AGENTS.md)：開発環境、回帰テスト
