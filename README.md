# media-pitch-shifter

macOS で、動画や音声の再生速度と尺を保ったまま、選択した音声トラックのピッチを変える。ローカルファイルと YouTube 動画を GUI と CLI で扱える。

## 使い方

### CLI

```sh
uv run pitch_shift.py input.mp4 output.mp4 -p -2.5 --audio-track 0 -F
```

`-p` に半音数を指定する。たとえば `-2.5` で 2.5 半音下がる。`--audio-track` は 0 始まりで、省略時は最初の音声トラックを使う。`-F` でフォルマントを保持する。出力先には、既存のフォルダ内で使われていないファイル名を指定する。

YouTube 動画を変換するときは、入力に URL を引用符で囲んで指定する。指定した出力先に変換結果を保存する。

```sh
uv run pitch_shift.py "https://www.youtube.com/watch?v=VIDEO_ID" output.mp4 -p -2.5 -F
```

### GUI

- ローカルファイルを使うときは、Finder から動画または音声ファイルを 1 つドロップする。
- YouTube 動画を使うときは、「YouTube URL」にリンクを貼り付ける。「ダウンロード先」の「選択…」でフォルダを指定し、「yt-dlpで取得」を押す。動画は `動画タイトル [動画ID].mp4` として保存され、自動的に変換対象になる。

「Pitch (st)」で半音数を指定する。「出力形式」が表示された場合は形式を選ぶ。音声トラックが複数ある場合は「音声トラック」で対象を変えられる。「変換」を押すと、結果は元ファイルと同じフォルダに保存される。たとえば `song.mp4` を初期設定の「Postfix」で変換すると `song_shift.mp4` になる。

## 初回セットアップ

`uv`、`ffmpeg`、`ffprobe`、`rubberband` が必要。YouTube 動画の取得には Deno 2.3 以降も必要。`yt-dlp` と YouTube の JavaScript チャレンジに必要なスクリプトは環境の同期時に入る。 [yt-dlp の JavaScript セットアップガイド](https://github.com/yt-dlp/yt-dlp/wiki/EJS)

```sh
uv sync --python 3.12
```

Rubber Band 4.0.0 の公式 CLI を使う場合は、環境の同期後に `rubberband` を `.venv/bin/` に置く。 [Rubber Band 公式配布ページ](https://breakfastquay.com/rubberband/)

### Finder から GUI を起動する

```sh
uv run python setup.py py2app -A
```

Finder で `dist/Media Pitch Shifter.app` をダブルクリックする。Python ソースを変更した場合はアプリを開き直す。

## 関連ドキュメント

- 入力・出力形式、保存と上書き、音声処理の詳細。 [仕様書](SPEC.md)
- 開発環境の扱いと回帰テストの実行方法。 [プロジェクトの作業ルール](AGENTS.md)
