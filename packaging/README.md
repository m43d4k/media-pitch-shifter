# Media Pitch Shifter

## 概要

ローカルの動画・音声ファイルとYouTube動画に対応したmacOS用ピッチシフトアプリ。再生速度や長さを変えずに、音の高さを調整できる。

## 対応環境

- Apple Silicon
- macOS 14以降

## ビルド手順

`build-macos.sh` を実行する。

例：

```bash
bash path/to/build-macos.sh
```

事前の環境構築は不要。  

- 完了すると`build-macos.sh` と同じフォルダの `dist` に `Media Pitch Shifter.app` が作成される。
- ビルド後、動作に必要なのは `Media Pitch Shifter.app` のみ。
- `Media Pitch Shifter.app` を任意の場所に移動すれば、packaging フォルダは削除して構わない。

## アプリの使い方

1. 変換する素材を指定する。
   - **ファイル**：「ファイル」タブに動画・音声ファイルをドロップする。
   - **YouTube**：「YouTube」タブでURLと保存先を指定し、ダウンロードする。ダウンロードした動画はそのまま変換対象になる。
2. 「Pitch (st)」でピッチの変化量を半音単位で指定する（例：`-2.5` で2.5半音下げる）。
3. 「変換」を押す。変換されたファイルは元ファイルと同じフォルダに保存され、既定ではファイル名に `_shift` が付与される。

---

リポジトリ：https://github.com/m43d4k/media-pitch-shifter

開発：m43d4k（https://github.com/m43d4k）