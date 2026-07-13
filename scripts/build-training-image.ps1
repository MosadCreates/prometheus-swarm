<#
.SYNOPSIS
Builds the Prometheus Swarm training Docker image with cache-efficient strategy.

.DESCRIPTION
Uses Docker layer caching by default for fast incremental builds.
Only the pip layer is rebuilt when dependencies change.
Use -Force to bypass all cache (full redownload of torch, etc.).

Hotfix workflow for adding a single package:
  docker run --rm prometheus-training-base pip install new-package==1.0
  docker commit $(docker ps -lq) prometheus-training-base:latest

.PARAMETER Force
Full rebuild from the original Dockerfile with --no-cache.
Downloads all pip packages fresh (~1GB for torch+CUDA).
.PARAMETER Tag
Image tag to apply. Default: prometheus-training-base:latest
#>

param(
    [switch]$Force,
    [string]$Tag = "prometheus-training-base:latest"
)

$ErrorActionPreference = "Stop"
$dockerfile = "training/base_training_image/Dockerfile"
$baseName = "prometheus-training-base"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Prometheus Swarm Training Image Builder ===" -ForegroundColor Cyan
Write-Host ""

$timer = [System.Diagnostics.Stopwatch]::StartNew()

Set-Location -LiteralPath $repoRoot

if ($Force) {
    Write-Host "[build] Force rebuild from ${dockerfile} (no cache)..."
    docker build --no-cache -t $Tag -f $dockerfile .
    if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
} else {
    $existingId = docker images -q $baseName 2>$null
    if ($existingId) {
        Write-Host "[build] Found existing image ${baseName}, building with layer cache..." -ForegroundColor Green
        Write-Host "[build] Docker cache reuses unchanged layers. Only changed pip packages trigger download."
    } else {
        Write-Host "[build] No existing image found. Building from ${dockerfile}..."
        Write-Host "[build] First build downloads all dependencies (~1GB for torch + CUDA)."
    }
    docker build -t $Tag -f $dockerfile .
    if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
}

$timer.Stop()
Write-Host ""
Write-Host "[build] Complete. Tag: ${Tag}" -ForegroundColor Green
Write-Host "[build] Duration: $($timer.Elapsed.TotalSeconds.ToString('F1'))s"

docker images --filter "reference=${Tag}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
