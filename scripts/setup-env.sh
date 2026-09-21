#!/usr/bin/env bash
# 课序 · Linux/WSL 一次性工具链准备（用户级安装，无需管理员，可重复执行）
# 对应 scripts/setup-env.ps1
# 用法: bash scripts/setup-env.sh [--proxy http://127.0.0.1:7890] [--skip-android]
set -euo pipefail

PROXY=""
SKIP_ANDROID=0
while [ $# -gt 0 ]; do
  case "$1" in
    --proxy) PROXY="${2:-}"; shift 2 ;;
    --skip-android) SKIP_ANDROID=1; shift ;;
    -h|--help) echo "用法: bash scripts/setup-env.sh [--proxy URL] [--skip-android]"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

if [ -n "$PROXY" ]; then
  export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" http_proxy="$PROXY" https_proxy="$PROXY"
  export NO_PROXY="localhost,127.0.0.1,10.0.0.0/8" no_proxy="localhost,127.0.0.1,10.0.0.0/8"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SUPERCOURSE_TOOLS:-${XDG_DATA_HOME:-$HOME/.local/share}/supercourse-tools}"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG="$LOG_DIR/setup-env.log"
mkdir -p "$ROOT/dl" "$LOG_DIR"

say() { local line="[$(date +%H:%M:%S)] $*"; echo "$line"; echo "$line" >> "$LOG"; }
say "工具链准备开始（ROOT=$ROOT）"

grab() { # url dest
  local url="$1" dest="$2"
  if [ -f "$dest" ] && [ "$(stat -c%s "$dest" 2>/dev/null || echo 0)" -gt 1000000 ]; then
    say "已存在，跳过下载: $(basename "$dest")"; return 0
  fi
  say "下载 $url"
  curl -fL --retry 3 --connect-timeout 20 -o "$dest" "$url"
}

extract_zip() { # zip into
  local zip="$1" into="$2" tmp="$2.__tmp"
  rm -rf "$tmp"
  say "解压 $(basename "$zip") -> $(basename "$into")"
  python3 -m zipfile -e "$zip" "$tmp"
  # zipfile 不保留可执行位，统一补上
  find "$tmp" -type f \( -name '*.sh' -o -path '*/bin/*' \) -exec chmod +x {} + 2>/dev/null || true
  rm -rf "$into"
  mkdir -p "$(dirname "$into")"
  mv "$tmp" "$into"
}

find_bin() { find "$1" -type f -name "$2" 2>/dev/null | head -1 || true; }

# --- 1) Temurin JDK 21（linux x64，只喂安卓工程，不改系统 Java）---
JDK_ROOT="$ROOT/jdk21"
JDK_JAVA="$(find_bin "$JDK_ROOT" java)"
if [ -z "$JDK_JAVA" ]; then
  grab "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse" "$ROOT/dl/jdk21.tar.gz"
  rm -rf "$JDK_ROOT"; mkdir -p "$JDK_ROOT"
  tar -xzf "$ROOT/dl/jdk21.tar.gz" -C "$JDK_ROOT" --strip-components=1
  JDK_JAVA="$(find_bin "$JDK_ROOT" java)"
else
  say "JDK 21 已就绪"
fi
[ -n "$JDK_JAVA" ] || { echo "JDK 21 安装失败：找不到 java" >&2; exit 1; }
export JAVA_HOME="$(dirname "$(dirname "$JDK_JAVA")")"
say "JAVA_HOME = $JAVA_HOME"

# --- 2) uv ---
if ! command -v uv >/dev/null 2>&1; then
  say "安装 uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV_BIN="$(command -v uv || true)"
[ -z "$UV_BIN" ] && UV_BIN="$HOME/.local/bin/uv"
say "uv = $("$UV_BIN" --version)"

# --- 3) Python 3.10.12（与服务器同版本，杜绝版本漂移）---
say "安装 CPython 3.10.12（uv 管理，已装则秒过）"
"$UV_BIN" python install 3.10.12

# --- 4) Android cmdline-tools + SDK ---
SDK_ROOT="$ROOT/Android/Sdk"
CMDLINE="$SDK_ROOT/cmdline-tools/latest"
SDKMANAGER="$CMDLINE/bin/sdkmanager"
if [ "$SKIP_ANDROID" -eq 0 ]; then
  if [ ! -x "$SDKMANAGER" ]; then
    grab "https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip" "$ROOT/dl/cmdline.zip"
    extract_zip "$ROOT/dl/cmdline.zip" "$ROOT/Android/cmdline-raw"
    mkdir -p "$SDK_ROOT/cmdline-tools"
    if [ -d "$ROOT/Android/cmdline-raw/cmdline-tools" ] && [ ! -d "$CMDLINE" ]; then
      mv "$ROOT/Android/cmdline-raw/cmdline-tools" "$CMDLINE"
    fi
  else
    say "cmdline-tools 已就绪"
  fi
  [ -x "$SDKMANAGER" ] || { echo "Android cmdline-tools 安装失败：找不到 sdkmanager" >&2; exit 1; }
  chmod +x "$CMDLINE/bin/"* 2>/dev/null || true
  export ANDROID_HOME="$SDK_ROOT"
  say "接受 SDK 许可"
  set +o pipefail
  yes | "$SDKMANAGER" --sdk_root="$SDK_ROOT" --licenses >/dev/null 2>&1 || true
  set -o pipefail
  say "安装 platform-tools / platforms;android-35 / build-tools;35.0.0（约 1GB，耐心等待）"
  set +o pipefail
  yes | "$SDKMANAGER" --sdk_root="$SDK_ROOT" "platform-tools" "platforms;android-35" "build-tools;35.0.0"
  set -o pipefail
else
  say "跳过 Android SDK（--skip-android）"
fi

# --- 5) 导出给其它脚本复用的环境片段 ---
cat > "$SCRIPT_DIR/tools-env.sh" <<EOF
# 自动生成，勿手改：由 scripts/setup-env.sh 写入
export JAVA_HOME="$JAVA_HOME"
export ANDROID_HOME="$SDK_ROOT"
export PATH="$JAVA_HOME/bin:$SDK_ROOT/platform-tools:\$PATH"
EOF
say "已生成 scripts/tools-env.sh（其它脚本 source 它即可）"

# --- 6) 自检表 ---
say "================ 环境自检 ================"
{
  printf "%-14s %s\n" "JDK21"      "$("$JAVA_HOME/bin/java" -version 2>&1 | head -1)"
  printf "%-14s %s\n" "uv"         "$("$UV_BIN" --version)"
  printf "%-14s %s\n" "Python-3.10" "$("$UV_BIN" python list --only-installed 2>/dev/null | grep -o '3\.10\.[0-9]*' | head -1 || echo '缺失')"
  printf "%-14s %s\n" "Node"       "$(node -v 2>/dev/null || echo 缺失)"
  printf "%-14s %s\n" "npm"        "$(npm -v 2>/dev/null || echo 缺失)"
  printf "%-14s %s\n" "git"        "$(git --version 2>/dev/null || echo 缺失)"
  printf "%-14s %s\n" "gh"         "$(gh --version 2>/dev/null | head -1 || echo 缺失)"
} | tee -a "$LOG"
say "工具链准备完成。下一步: cd server && uv sync  以及根目录 npm ci"
