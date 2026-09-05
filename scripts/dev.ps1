$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path

Write-Host "Starting backend http://127.0.0.1:8090"
$backend = Start-Process -FilePath (Join-Path $root "server\.venv\Scripts\uvicorn.exe") `
  -ArgumentList "app.main:app", "--host", "127.0.0.1", "--port", "8090", "--reload", "--reload-dir", (Join-Path $root "server\app") `
  -WorkingDirectory (Join-Path $root "server") `
  -PassThru `
  -WindowStyle Hidden

Write-Host "Starting frontend http://127.0.0.1:5173"
$frontend = Start-Process -FilePath (Join-Path $root "node_modules\.bin\vite.cmd") `
  -ArgumentList "--host" `
  -WorkingDirectory (Join-Path $root "apps\web") `
  -PassThru `
  -WindowStyle Hidden

try {
  $deadline = (Get-Date).AddSeconds(20)
  do {
    Start-Sleep -Milliseconds 250
    $ready = $true
    try {
      Invoke-WebRequest -Uri "http://127.0.0.1:8090/api/health" -UseBasicParsing | Out-Null
    } catch {
      $ready = $false
    }
  } while (-not $ready -and (Get-Date) -lt $deadline)

  Write-Host "Backend ready, opening http://127.0.0.1:5173"
  Start-Process "http://127.0.0.1:5173"

  Write-Host "Dev servers started (backend PID $($backend.Id) / frontend PID $($frontend.Id))."
} catch {
  Write-Warning "Backend timed out or opening the browser failed. Please visit http://127.0.0.1:5173 manually."
}
