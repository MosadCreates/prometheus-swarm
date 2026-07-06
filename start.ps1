param(
  [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
$rootDir = $PSScriptRoot
$frontendDir = Join-Path $rootDir "frontend"
$venvDir = Join-Path $rootDir ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"

Write-Host "Prometheus Swarm - Starting" -ForegroundColor Cyan
Write-Host ""

# Verify prerequisites
if (-not (Test-Path $pythonExe)) {
  Write-Host "ERROR: Python venv not found at $venvDir" -ForegroundColor Red
  exit 1
}

# Check Docker running
$dockerInfo = docker info --format "{{.ServerVersion}}" 2>$null
if ($dockerInfo) {
  Write-Host "Docker engine running (v$dockerInfo)" -ForegroundColor Green
} else {
  Write-Host "Docker engine not reachable - Furnace training will fail" -ForegroundColor Yellow
}

# Check Redis reachable
$redisCheckScript = "import redis; r=redis.Redis('localhost',6379,decode_responses=True); r.ping(); print('ok')"
$redisResult = & $pythonExe -c $redisCheckScript 2>$null
if ($redisResult -eq "ok") {
  Write-Host "Redis reachable (localhost:6379)" -ForegroundColor Green
} else {
  Write-Host "Redis not reachable - start it with: docker run -d -p 6379:6379 redis:7" -ForegroundColor Red
  exit 1
}

# Clean up stale Redis consumer groups so old messages are re-processed
Write-Host "Cleaning consumer groups..." -ForegroundColor Cyan
& $pythonExe (Join-Path $rootDir "scripts\clean_consumer_groups.py") 2>$null

# Kill leftover orchestrator process
$oldProc = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*orchestrator*" }
if ($oldProc) {
  $oldProc | Stop-Process -Force
  Write-Host "Stopped stale orchestrator process" -ForegroundColor Yellow
}

# Start orchestrator in background job
$orchLog = Join-Path $rootDir "orch_output.log"
Write-Host "Starting orchestrator... (logs -> orch_output.log)" -ForegroundColor Cyan
$orchJob = Start-Job -Name "orch" -ScriptBlock {
  param($py, $dir, $log)
  Set-Location $dir
  $env:PYTHONUNBUFFERED = "1"
  & $py "orchestrator\runtime.py" *>> $log
} -ArgumentList $pythonExe, $rootDir, $orchLog

# Poll Redis heartbeat to confirm orchestrator is alive (up to 20s)
$heartbeatScript = "import redis; r=redis.Redis('localhost',6379,decode_responses=True); print(r.get('orch:heartbeat') or '')"
$orchReady = $false
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Seconds 1
  $hb = & $pythonExe -c $heartbeatScript 2>$null
  if ($hb) { $orchReady = $true; break }
}
if ($orchReady) {
  Write-Host "Orchestrator running" -ForegroundColor Green
} else {
  Write-Host "Orchestrator start timed out (check orch_output.log)" -ForegroundColor Red
  if (-not $NoFrontend) {
    Write-Host "Starting frontend only..." -ForegroundColor Yellow
  }
}

function Cleanup {
  Write-Host "Shutting down..." -ForegroundColor Cyan
  Get-Job -Name "orch" -ErrorAction SilentlyContinue | Stop-Job
  Get-Job -Name "orch" -ErrorAction SilentlyContinue | Remove-Job
  exit
}

if ($NoFrontend) {
  Write-Host "Orchestrator running. Press Ctrl+C to stop." -ForegroundColor Green
  try {
    while ($true) { Start-Sleep -Seconds 1 }
  } finally { Cleanup }
} else {
  Write-Host "Starting Next.js dev server..." -ForegroundColor Cyan
  Write-Host "Open http://localhost:3000 to use the app" -ForegroundColor Green
  Write-Host ""

  try {
    Push-Location $frontendDir
    npm run dev
    Pop-Location
  } finally {
    Cleanup
  }
}
