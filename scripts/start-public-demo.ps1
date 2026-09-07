#Requires -Version 5.1
<#
.SYNOPSIS
  Starts the enterprise-rag-platform stack locally for the $0 self-hosted
  public demo (docs/SELF_HOSTED_PUBLIC_DEMO.md). Does NOT start a Cloudflare
  Tunnel -- it prints the command for that as its last step, so exposing this
  machine to the public internet stays a deliberate, visible action you take
  yourself, not something a script does silently on your behalf.

.DESCRIPTION
  1. Checks Docker Desktop is running.
  2. Runs `docker compose up -d --build`.
  3. Polls GET /health/ready on the api service until it's ready (or times out).
  4. Verifies the frontend is serving (GET /healthz through nginx).
  5. Prints the local URL and the cloudflared command to expose it publicly.

  Stores no credentials, no tokens, no config. Reads only whatever .env
  already sets (or docker-compose.yml's baked-in local defaults if there is
  no .env) -- this script does not create, edit, or read secret values itself.

.PARAMETER TimeoutSeconds
  How long to wait for /health/ready before giving up. Default 180 -- first
  run downloads the fastembed/reranker ONNX models (~150MB) into the
  `modelcache` volume, which takes longer than a warm restart.
#>

[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

# Resolve the repo root relative to this script, so it works regardless of
# the caller's current directory.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$ApiHealthUrl = "http://127.0.0.1:8000/health/ready"
$ApiLiveUrl = "http://127.0.0.1:8000/health/live"
$FrontendUrl = "http://127.0.0.1:8080/healthz"
$AppUrl = "http://localhost:8080"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Fail {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
}

Write-Step "Checking Docker Desktop is running"
try {
    docker version --format '{{.Server.Version}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker version exited non-zero" }
}
catch {
    Write-Fail "Docker does not appear to be running. Start Docker Desktop, wait for it to finish starting, then re-run this script."
    exit 1
}
Write-Host "Docker is up."

Write-Step "Starting the stack (docker compose up -d --build)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Fail "docker compose up failed -- see the output above."
    exit 1
}

Write-Step "Waiting for the API to become ready (up to $TimeoutSeconds s)"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready = $false
$lastDetail = ""
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri $ApiHealthUrl -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
        $lastDetail = $resp.Content
    }
    catch {
        # Not up yet (connection refused / 503 while dependencies come up) -- keep polling.
        if ($_.Exception.Response) {
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $lastDetail = $reader.ReadToEnd()
            }
            catch {
                $lastDetail = $_.Exception.Message
            }
        }
        else {
            $lastDetail = $_.Exception.Message
        }
    }
    Start-Sleep -Seconds 3
    Write-Host "." -NoNewline
}
Write-Host ""

if (-not $ready) {
    Write-Fail "API did not report ready within $TimeoutSeconds s."
    Write-Host "Last readiness response: $lastDetail"
    Write-Host "Checking liveness instead (process-up only, no dependency checks):"
    try {
        $live = Invoke-WebRequest -Uri $ApiLiveUrl -UseBasicParsing -TimeoutSec 5
        Write-Host "  /health/live -> $($live.StatusCode) $($live.Content)"
    }
    catch {
        Write-Host "  /health/live also unreachable: $($_.Exception.Message)"
    }
    Write-Host ""
    Write-Host "Run 'docker compose logs api' and 'docker compose logs bootstrap' to diagnose."
    exit 1
}
Write-Host "API is ready."

Write-Step "Verifying the frontend"
try {
    $fe = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec 10
    if ($fe.StatusCode -ne 200) { throw "unexpected status $($fe.StatusCode)" }
    Write-Host "Frontend is serving."
}
catch {
    Write-Fail "Frontend health check failed: $($_.Exception.Message)"
    Write-Host "Run 'docker compose logs frontend' to diagnose."
    exit 1
}

Write-Step "Stack is up"
Write-Host "Local application URL: $AppUrl" -ForegroundColor Green
Write-Host ""
Write-Host "To expose this publicly with a free Cloudflare Quick Tunnel, run in a" -ForegroundColor Yellow
Write-Host "SEPARATE terminal (this keeps running as long as that window is open" -ForegroundColor Yellow
Write-Host "and the stack above stays up):" -ForegroundColor Yellow
Write-Host ""
Write-Host "    cloudflared tunnel --url $AppUrl" -ForegroundColor White
Write-Host ""
Write-Host "cloudflared will print your public https://*.trycloudflare.com URL" -ForegroundColor Yellow
Write-Host "once it connects. No login or account is required for a Quick Tunnel." -ForegroundColor Yellow
Write-Host "See docs/SELF_HOSTED_PUBLIC_DEMO.md for the full guide, including the" -ForegroundColor Yellow
Write-Host "named-tunnel path (stable hostname) if you get a domain later." -ForegroundColor Yellow
