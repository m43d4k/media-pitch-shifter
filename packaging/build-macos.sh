#!/bin/bash
set -Eeuo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV CONDA_PREFIX

phase=起動条件の確認
trap 'printf "失敗した工程: %s\n" "$phase" >&2' ERR

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || \
    fail "このビルドは Apple Silicon Mac に対応しています。"
os_version=$(sw_vers -productVersion)
[[ ${os_version%%.*} -ge 14 ]] || fail "macOS 14 以降が必要です。"

CDPATH= cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")"
script_dir=$PWD
[[ $# -eq 0 ]] || fail "使い方: /bin/bash build-macos.sh"

phase=ビルド設定の確認
config_file="$script_dir/macos-build.conf"
[[ -f "$config_file" ]] || fail "スクリプトと同じフォルダに macos-build.conf を置いてください。"
config_keys=(
    PYTHON_VERSION CCTOOLS_VERSION CCTOOLS_TOOL_PREFIX RUBBERBAND_VERSION
    UV_URL UV_SHA256 CCTOOLS_URL CCTOOLS_SHA256 OUCH_URL OUCH_SHA256
    FFMPEG_URL FFMPEG_SHA256 FFPROBE_URL FFPROBE_SHA256 RUBBERBAND_URL RUBBERBAND_SHA256
    YTDLP_URL YTDLP_SHA256 DENO_URL DENO_SHA256
)
unset "${config_keys[@]}"
source "$config_file"

for key in "${config_keys[@]}"; do
    value=${!key:-}
    [[ -n $value ]] || fail "$key が設定されていません。"
    case $key in
        *_URL) [[ $value == https://?* && $value != *[[:space:]]* ]] ||
            fail "$key に HTTPS URL を指定してください。" ;;
        *_SHA256) [[ $value =~ ^[0-9a-fA-F]{64}$ ]] ||
            fail "$key に16進数64桁の SHA-256 を指定してください。" ;;
        *) [[ $value =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] ||
            fail "$key に使用できない文字が含まれています。" ;;
    esac
done

phase=ソースの確認
source_dir="$script_dir/src"
for file in pyproject.toml uv.lock pitch_shift_gui.py pitch_shift.py assets/AppIcon.icns; do
    [[ -f "$source_dir/$file" ]] || fail "同梱の src/$file がありません。配布 ZIP をフォルダごと展開してください。"
done

phase=作業フォルダの準備
mkdir -p "$script_dir/build"
work=$(mktemp -d "$script_dir/build/macos.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
export TMPDIR="$work/tmp"
export UV_CACHE_DIR="$work/uv-cache" UV_PYTHON_INSTALL_DIR="$work/python"
export UV_PROJECT_ENVIRONMENT="$work/venv" PYINSTALLER_CONFIG_DIR="$work/pyinstaller"
export XDG_CACHE_HOME="$work/cache" XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data"
mkdir -p "$TMPDIR" "$work/bin" "$work/downloads"

download() {
    local url=$1 checksum=$2 destination=$3
    curl -q --proto '=https' --proto-redir '=https' --fail --silent --show-error \
        --location --retry 2 --globoff --output "$destination" -- "$url"
    printf '%s  %s\n' "$checksum" "$destination" | shasum -a 256 --check --status || \
        fail "SHA-256 が一致しません（${destination##*/}）。"
}

phase=ビルドツールの取得
printf '%s\n' "$phase"
downloads="$work/downloads"
download "$UV_URL" "$UV_SHA256" "$downloads/uv.tar.gz"
tar -xzf "$downloads/uv.tar.gz" --strip-components=1 -C "$work/bin" uv-aarch64-apple-darwin/uv

phase='Mach-O ビルドツールの準備'
printf '%s\n' "$phase"
# PyInstaller が呼ぶ Mach-O ツールを作業フォルダ内に用意する。
cctools="cctools_impl_osx-arm64-$CCTOOLS_VERSION"
download "$CCTOOLS_URL" "$CCTOOLS_SHA256" "$downloads/cctools.conda"
unzip -qp "$downloads/cctools.conda" "pkg-$cctools.tar.zst" > "$downloads/cctools.tar.zst"
download "$OUCH_URL" "$OUCH_SHA256" "$downloads/ouch.tar.gz"
tar -xzf "$downloads/ouch.tar.gz" --strip-components=1 -C "$work/bin" ouch-aarch64-apple-darwin/ouch
mkdir "$work/cctools"
"$work/bin/ouch" decompress --quiet --dir "$work/cctools" "$downloads/cctools.tar.zst"
for tool in lipo install_name_tool; do
    install -m 755 "$work/cctools/bin/$CCTOOLS_TOOL_PREFIX-$tool" "$work/bin/$tool"
done
export PATH="$work/bin:$PATH"

phase=Python環境の作成
printf '%s\n' "$phase"
cd -- "$source_dir"
uv --no-config sync --locked --only-group macos-build --no-build --managed-python \
    --python "$PYTHON_VERSION"

phase=アプリのビルド
printf '%s\n' "$phase"
app_name='Media Pitch Shifter'
"$UV_PROJECT_ENVIRONMENT/bin/python" -m PyInstaller --log-level WARN \
    --windowed --onedir --name "$app_name" --target-arch arm64 \
    --osx-bundle-identifier local.media-pitch-shifter --icon "$source_dir/assets/AppIcon.icns" \
    --distpath "$work/output" --workpath "$work/pyinstaller-work" --specpath "$work" \
    "$source_dir/pitch_shift_gui.py"

phase=外部コマンドの取得
printf '%s\n' "$phase"
download "$FFMPEG_URL" "$FFMPEG_SHA256" "$downloads/ffmpeg.zip"
download "$FFPROBE_URL" "$FFPROBE_SHA256" "$downloads/ffprobe.zip"
download "$RUBBERBAND_URL" "$RUBBERBAND_SHA256" "$downloads/rubberband.tar.bz2"
download "$YTDLP_URL" "$YTDLP_SHA256" "$downloads/yt-dlp.zip"
download "$DENO_URL" "$DENO_SHA256" "$downloads/deno.zip"

phase=同梱ファイルとアプリの検証
printf '%s\n' "$phase"
app="$work/output/$app_name.app"
helpers="$app/Contents/Helpers"
mkdir "$helpers"
for tool in ffmpeg ffprobe deno; do
    unzip -qp "$downloads/$tool.zip" "$tool" > "$helpers/$tool"
done
rubberband_dir="rubberband-$RUBBERBAND_VERSION-gpl-executable-macos"
tar -xOf "$downloads/rubberband.tar.bz2" "$rubberband_dir/rubberband" > "$helpers/rubberband"
chmod 755 "$helpers/"*
for tool in ffmpeg ffprobe rubberband deno; do
    codesign --force --sign - "$helpers/$tool"
done
"$helpers/ffmpeg" -version > /dev/null
"$helpers/ffprobe" -version > /dev/null
"$helpers/rubberband" --version > /dev/null 2>&1
"$helpers/deno" --version > /dev/null

# 公式の展開済み構成を保ち、yt-dlp の実行ファイルと _internal を隣り合わせに置く。
yt_dlp_dir="$app/Contents/Resources/yt-dlp"
ditto -x -k "$downloads/yt-dlp.zip" "$yt_dlp_dir"
mv "$yt_dlp_dir/yt-dlp_macos" "$yt_dlp_dir/yt-dlp"
"$yt_dlp_dir/yt-dlp" --version > /dev/null
tar -xOf "$downloads/rubberband.tar.bz2" "$rubberband_dir/COPYING" \
    > "$app/Contents/Resources/RubberBand-COPYING.txt"
plutil -replace LSMinimumSystemVersion -string 14.0 "$app/Contents/Info.plist"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"

phase=完成したアプリの配置
mkdir -p "$script_dir/dist"
output=$(mktemp -d "$script_dir/dist/macos-arm64.XXXXXXXX")
mv "$app" "$output/"
printf '\nビルド完了\n%s\n' "$output/$app_name.app"
