# 启动真实数据 e2e 后端：seed + 签发 token + 起 uvicorn（隔离数据目录）。
$ErrorActionPreference = "Stop"
$serverDir = Join-Path $PSScriptRoot "..\..\..\server"
$dataDir = Join-Path $serverDir ".e2e-data"
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "media") | Out-Null

Push-Location $serverDir
$env:SC_DATA_DIR = $dataDir
& ".\.venv\Scripts\python.exe" -m scripts.e2e_init
if ($LASTEXITCODE -ne 0) { Write-Host "e2e_init failed"; exit $LASTEXITCODE }
# 前台运行 uvicorn（阻塞，Playwright webServer 认为后端进程存活直到 kill）。
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host localhost --port 8090
Pop-Location
