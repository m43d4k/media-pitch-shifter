# media-pitch-shifter

動画・音声の再生速度と長さを変えずに、ピッチを変更するmacOS用ツール。ローカルファイルとYouTube動画に対応。

## macOSアプリ

[GitHub Releases](https://github.com/m43d4k/media-pitch-shifter/releases)で配布用ビルドキットを公開。ビルド手順と操作方法は同梱の [README](packaging/README.md) を参照。

## GUIの使い方

1. 変換する素材を指定する。
   - ファイル：「ファイル」タブに動画・音声をドロップする。
   - YouTube：「YouTube」タブでURLと保存先を指定してダウンロードする。取得中は工程と進捗率を表示し、保存後は「ダウンロード完了」と保存先を表示する。取得した動画はそのまま変換対象になる。
2. 「Pitch (st)」でピッチの変化量を半音単位で指定する。フォルマント保持も設定できる。
3. 「変換」を押す。処理中は進捗バーに現在の工程とその進捗率を表示する。進捗率を取得できない間はバーが動く。保存が終わると「変換完了」とファイル名を表示する。変換されたファイルは元ファイルと同じフォルダに保存され、既定ではファイル名に `_shift` が付与される。
4. 変換が完了したら、「変換」の右隣に表示される「Finderで開く」を押すと、保存したファイルがFinderで選択される。「閉じる」を押すとウィンドウが閉じる。

## 開発環境

必要環境：macOS、`uv`、FFmpeg（`ffmpeg`・`ffprobe`）、Deno 2.3以降。

### Python依存ライブラリ

リポジトリのルートで実行する。

```sh
uv sync
```

### Rubber Band

公式配布のRubber Band 4.0.0 macOS用CLIを `.venv/bin/rubberband` に配置する。

[Rubber Band公式サイト](https://breakfastquay.com/rubberband/)

```sh
# ダウンロード・展開
tmp=$(mktemp -d)
curl -fsSL https://breakfastquay.com/files/releases/rubberband-4.0.0-gpl-executable-macos.tar.bz2 -o "$tmp/rubberband.tar.bz2"
tar -xjf "$tmp/rubberband.tar.bz2" -C "$tmp"

# 配置・後片付け
install -m 755 "$tmp/rubberband-4.0.0-gpl-executable-macos/rubberband" .venv/bin/rubberband
rm -rf "$tmp"
```

### CLI

```sh
# ローカルファイル
uv run pitch_shift.py input.mp4 output.mp4 -p -2.5 --audio-track 0 -F

# YouTube
uv run pitch_shift.py "https://www.youtube.com/watch?v=VIDEO_ID" output.mp4 -p -2.5 -F
```

- `-p`：変更する半音数
- `--audio-track`：音声トラック番号（0始まり、既定は0）
- `-F`：フォルマント保持

既存ファイルへの上書きは不可。

### GUIアプリのビルド（開発用）

py2appのエイリアスモードを使用する。

```sh
uv run python setup.py py2app -A
```

出力先：`dist/Media Pitch Shifter.app`

## リリース

## リリース

リポジトリのルートで以下を実行し、最新のコミット（HEAD）から配布用ZIPを作成する。作成したZIPをGitHub Releaseに添付する。

```bash
git archive --format=zip \
  --prefix=media-pitch-shifter-build/ \
  --add-file=packaging/README.md \
  --output=media-pitch-shifter-build.zip \
  HEAD \
  pitch_shift.py pitch_shift_gui.py assets pyproject.toml uv.lock \
  packaging/build-macos.sh packaging/macos-build.conf
```

## 関連ドキュメント

- [仕様書](SPEC.md)：対応形式、保存・上書き、音声処理
- [作業ルール](AGENTS.md)：開発環境、回帰テスト
