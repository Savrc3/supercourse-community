# 超课表 · 一次性工具链准备（用户级 zip 安装，无需管理员，可重复执行）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-env.ps1 [-Proxy http://127.0.0.1:7890] [-SkipAndroid]
param(
  [string]$Proxy = "",
  [switch]$SkipAndroid
)
$ErrorActionPreference = "Stop"
$Root = Join-Path $env:LOCALAPPDATA "supercourse-tools"
$logDir = Join-Path $PSScriptRoot "..logs"
$log = Join-Path $logDir "setup-env.log"
New-Item -ItemType Directory -Force -Path $Root, $logDir, (Join-Path $Root "dl") | Out-Null
if ($Proxy) { $env:HTTP_PROXY = $Proxy; $env:HTTPS_PROXY = $Proxy; $env:NO_PROXY = "localhost,127.0.0.1,10.0.0.0/8" }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say($m) {
  $line = "[" + (Get-Date -Format HH:mm:ss) + "] " + $m
  Write-Host $line
  Add-Content -Path $log -Value $line -Encoding UTF8
}

function Grab($url, $dest) {
  if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 1MB)) { Say ("已存在，跳过下载: " + (Split-Path $dest -Leaf)); return }
  Say ("下载 " + $url)
  Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

# 解压后统一用"搜索关键文件"定位，绝不猜目录名
function Find-Exe($dir, $name) {
  if (-not (Test-Path $dir)) { return $null }
  $hit = Get-ChildItem -LiteralPath $dir -Recurse -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($hit) { return $hit.FullName }
  return $null
}

function ExtractZip($zip, $into) {
  $tmp = $into + ".__tmp"
  if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
  Say ("解压 " + (Split-Path $zip -Leaf) + " -> " + (Split-Path $into -Leaf))
  Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
  if (Test-Path $into) { Remove-Item $into -Recurse -Force }
  New-Item -ItemType Directory -Force -Path (Split-Path $into) | Out-Null
  Move-Item -LiteralPath $tmp -Destination $into
}

# --- 1) Temurin JDK 21（只喂安卓工程，不改系统 Java）---
$jdkRoot = Join-Path $Root "jdk21"
$jdkJava = Find-Exe $jdkRoot "java.exe"
if (-not $jdkJava) {
  Grab "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse" (Join-Path $Root "dl\jdk21.zip")
  ExtractZip (Join-Path $Root "dl\jdk21.zip") $jdkRoot
  $jdkJava = Find-Exe $jdkRoot "java.exe"
} else { Say "JDK 21 已就绪" }
if (-not $jdkJava) { throw "JDK 21 安装失败：找不到 java.exe" }
$jdkHome = (Get-Item $jdkJava).Directory.Parent.FullName
Say ("JAVA_HOME = " + $jdkHome)

# --- 2) uv（Python 版本与虚拟环境管理器）---
$uvDir = Join-Path $Root "uv"
$uvExe = Find-Exe $uvDir "uv.exe"
if (-not $uvExe) {
  Grab "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" (Join-Path $Root "dl\uv.zip")
  ExtractZip (Join-Path $Root "dl\uv.zip") $uvDir
  $uvExe = Find-Exe $uvDir "uv.exe"
} else { Say "uv 已就绪" }
if (-not $uvExe) { throw "uv 安装失败：找不到 uv.exe" }
$env:Path = (Split-Path $uvExe) + ";" + $env:Path

# --- 3) Python 3.10.12（与服务器同版本，杜绝版本漂移）---
Say "安装 CPython 3.10.12（uv 管理，已装则秒过）"
& $uvExe python install 3.10.12
if ($LASTEXITCODE -ne 0) { throw "uv python install 失败，可加 -Proxy http://127.0.0.1:7890 重试" }

# --- 4) Android cmdline-tools + SDK（不装 Android Studio，见 D-24）---
$sdkRoot = Join-Path $Root "Android\Sdk"
$cmdline = Join-Path $sdkRoot "cmdline-tools\latest"
$sdkmanager = Join-Path $cmdline "bin\sdkmanager.bat"
if (-not $SkipAndroid) {
  if (-not (Test-Path $sdkmanager)) {
    Grab "https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip" (Join-Path $Root "dl\cmdline.zip")
    ExtractZip (Join-Path $Root "dl\cmdline.zip") (Join-Path $Root "Android\cmdline-raw")
    New-Item -ItemType Directory -Force -Path (Join-Path $sdkRoot "cmdline-tools") | Out-Null
    $moved = Join-Path $Root "Android\cmdline-raw\cmdline-tools"
    if ((Test-Path $moved) -and (-not (Test-Path $cmdline))) { Move-Item $moved $cmdline }
  } else { Say "cmdline-tools 已就绪" }
  if (-not (Test-Path $sdkmanager)) { throw "Android cmdline-tools 安装失败：找不到 sdkmanager.bat" }
  $env:ANDROID_HOME = $sdkRoot
  $env:JAVA_HOME = $jdkHome
  $yes = ("y" + [char]13 + [char]10) * 60
  Say "接受 SDK 许可"
  $yes | & $sdkmanager --sdk_root=$sdkRoot --licenses | Select-Object -Last 3
  Say "安装 platform-tools / platforms;android-35 / build-tools;35.0.0（约 1GB，耐心等待）"
  $yes | & $sdkmanager --sdk_root=$sdkRoot "platform-tools" "platforms;android-35" "build-tools;35.0.0" | Select-Object -Last 3
}

# --- 5) 导出给其它脚本复用的环境片段 ---
$envLines = @(
  "# 自动生成，勿手改：由 scripts/setup-env.ps1 写入",
  ('$env:JAVA_HOME = "' + $jdkHome + '"'),
  ('$env:ANDROID_HOME = "' + $sdkRoot + '"'),
  ('$env:Path = "' + (Split-Path $uvExe) + ';" + $env:Path')
)
Set-Content -LiteralPath (Join-Path $PSScriptRoot "tools-env.ps1") -Value $envLines -Encoding UTF8
Say "已生成 scripts/tools-env.ps1（其它脚本 dot-source 它即可）"

# --- 6) 自检表 ---
# 注意：java/python/gh 都把版本信息写到 stderr，必须临时放宽 EAP，否则误判为缺失
function Ver($exe, $args2) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $raw = (& $exe @args2 2>&1) | Out-String
    $first = (($raw -split "\r?\n") | Where-Object { $_.Trim() -ne "" } | Select-Object -First 1)
    if ($first) { return $first.Trim() }
    return "缺失"
  } catch { return "缺失" } finally { $ErrorActionPreference = $prev }
}
$pyList = ((& $uvExe python list --only-installed 2>&1) -join " ; ")
$rows = @(
  [pscustomobject]@{ 组件 = "JDK21-安卓专用"; 实际 = (Ver $jdkJava @("-version")) },
  [pscustomobject]@{ 组件 = "系统Java-不动"; 实际 = (Ver "java" @("-version")) },
  [pscustomobject]@{ 组件 = "uv"; 实际 = (Ver $uvExe @("--version")) },
  [pscustomobject]@{ 组件 = "Python-3.10"; 实际 = $(if ($pyList -match "3\.10") { "已安装" } else { "缺失" }) },
  [pscustomobject]@{ 组件 = "Node"; 实际 = (Ver "node" @("-v")) },
  [pscustomobject]@{ 组件 = "npm"; 实际 = (Ver "npm" @("-v")) },
  [pscustomobject]@{ 组件 = "git"; 实际 = (Ver "git" @("--version")) },
  [pscustomobject]@{ 组件 = "gh"; 实际 = (Ver "gh" @("auth","status")) }
)
Say "================ 环境自检 ================"
$rows | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
Say "工具链准备完成。下一步: cd server; uv sync  以及根目录 npm install"
