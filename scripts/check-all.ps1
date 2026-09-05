$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$failed = $false

function Run($name, $block) {
  Write-Host "`n>>> $name"
  try {
    & $block
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$name failed with exit code $LASTEXITCODE" }
    Write-Host "<<< $name OK"
  } catch {
    Write-Host "<<< $name FAILED: $_"
    $script:failed = $true
  }
}

Push-Location (Join-Path $root "server")
Run "ruff check" { .venv\Scripts\python.exe -m ruff check . }
Run "ruff format" { .venv\Scripts\python.exe -m ruff format --check . }
Run "mypy" { .venv\Scripts\python.exe -m mypy app }
Run "pytest" { .venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-now }
Pop-Location

Push-Location $root
Run "eslint" { npm run lint --workspace @supercourse/web }
Run "vue-tsc" { npm run typecheck --workspace @supercourse/web }
Run "vitest" { npm run test --workspace @supercourse/web }
Run "frontend build" { npm run build --workspace @supercourse/web }
Run "desktop test" { npm run test --workspace @supercourse/desktop }
Pop-Location

$scanScript = Join-Path $env:USERPROFILE ".codex\skills\sensitive-scan\scripts\sensitive-scan.py"
if (Test-Path $scanScript) {
  & python $scanScript $root --exclude node_modules,dist
  if ($LASTEXITCODE -ne 0) { Write-Host "<<< sensitive scan 有命中（见上）。多为 127.0.0.1 回环 / JDK 版本 / git 身份，私有仓内部提交可接受；对外发布前必须清零。" } else { Write-Host "<<< sensitive scan OK" }
}

if ($failed) {
  throw "check-all failed"
} else {
  Write-Host "`ncheck-all passed"
}
