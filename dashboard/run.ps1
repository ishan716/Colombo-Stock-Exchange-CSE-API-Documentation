<#
.SYNOPSIS
    Start the CSE portfolio dashboard and open it in a browser.

.DESCRIPTION
    Creates .venv if missing, installs dependencies, waits for /api/health to
    answer, then opens the dashboard. Ctrl-C stops the server.

    Runs from any directory. The bash equivalent is run.sh.

.EXAMPLE
    .\dashboard\run.ps1
.EXAMPLE
    .\dashboard\run.ps1 -Port 8080 -NoBrowser
.EXAMPLE
    .\dashboard\run.ps1 -Reload
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    # Not -Host: $Host is a PowerShell automatic variable.
    [string]$BindHost = '127.0.0.1',
    [switch]$NoBrowser,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'

# Repo root, resolved from this script rather than the caller's location,
# because uvicorn must import dashboard.server.main as a package.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root '.venv'
$Url = "http://${BindHost}:${Port}"

function Say([string]$Message) { Write-Host "  $Message" }

function Test-Health {
    try {
        $r = Invoke-WebRequest -Uri "$Url/api/health" -TimeoutSec 2 `
                               -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-PortOpen {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($BindHost, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(1000, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# venv layout differs by platform: Scripts\python.exe on Windows (Python's "nt"
# install scheme), bin/python on POSIX. PowerShell Core runs on both.
function Get-VenvPython {
    foreach ($rel in 'Scripts\python.exe', 'bin/python') {
        $p = Join-Path $Venv $rel
        if (Test-Path $p -PathType Leaf) { return $p }
    }
    return $null
}

# A system python to build the venv with. The py launcher is preferred on
# Windows because `python` may be the Microsoft Store app-execution stub.
function Get-SystemPython {
    foreach ($candidate in @(
        @{ Exe = 'py';      Args = @('-3') },
        @{ Exe = 'python3'; Args = @() },
        @{ Exe = 'python';  Args = @() }
    )) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $probe = $candidate.Args + @('-c', 'import sys; sys.exit(sys.version_info[0] != 3)')
            & $candidate.Exe @probe 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {
            continue
        }
    }
    return $null
}

# --- already running? -------------------------------------------------------
# If something answers our health route on this port, it is this dashboard --
# just open it instead of failing on a port clash.
if (Test-Health) {
    Say "already running at $Url"
    if (-not $NoBrowser) { Start-Process $Url | Out-Null }
    exit 0
}

if (Test-PortOpen) {
    Write-Error "port $Port on $BindHost is in use by something that is not this dashboard.`ntry: .\dashboard\run.ps1 -Port $($Port + 1)"
    exit 1
}

# --- environment ------------------------------------------------------------
if (-not (Get-VenvPython)) {
    $sys = Get-SystemPython
    if (-not $sys) {
        Write-Error 'no Python 3 on PATH (tried py -3, python3, python)'
        exit 1
    }
    Say 'creating virtualenv at .venv'
    & $sys.Exe @($sys.Args + @('-m', 'venv', $Venv))
    if ($LASTEXITCODE -ne 0) { Write-Error 'could not create the virtualenv'; exit 1 }
}

$PyBin = Get-VenvPython
if (-not $PyBin) {
    Write-Error "virtualenv at $Venv has no python -- delete it and re-run"
    exit 1
}

& $PyBin -c 'import fastapi, uvicorn, httpx, websocket' 2>$null
if ($LASTEXITCODE -ne 0) {
    Say 'installing dependencies'
    & $PyBin -m pip install --quiet --upgrade pip
    & $PyBin -m pip install --quiet -r (Join-Path $Root 'dashboard\requirements.txt')
    if ($LASTEXITCODE -ne 0) { Write-Error 'dependency install failed'; exit 1 }
}

if (-not (Test-Path (Join-Path $Root 'dashboard\holdings.json') -PathType Leaf)) {
    Say 'no holdings.json yet -- starting with an empty portfolio'
    Say '  copy dashboard\holdings.sample.json dashboard\holdings.json'
}

# --- start ------------------------------------------------------------------
$UvArgs = @('-m', 'uvicorn', 'dashboard.server.main:app',
            '--host', $BindHost, '--port', $Port)
if ($Reload) { $UvArgs += '--reload' }

Say "starting server on $Url"
$proc = Start-Process -FilePath $PyBin -ArgumentList $UvArgs -NoNewWindow -PassThru

try {
    # Opening before the server answers would just show a connection error.
    $ready = $false
    foreach ($i in 1..60) {
        if ($proc.HasExited) {
            Write-Error 'server exited during startup -- see the output above'
            exit 1
        }
        if (Test-Health) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }

    if ($ready) {
        if (-not $NoBrowser) {
            Start-Process $Url | Out-Null
        } else {
            Say "ready at $Url"
        }
    } else {
        Say 'server did not answer /api/health in 30s; leaving it running'
        Say "try $Url yourself"
    }

    Say 'Ctrl-C to stop'
    Wait-Process -Id $proc.Id
} finally {
    if (-not $proc.HasExited) {
        $proc.Kill()
        try { $proc.WaitForExit(5000) | Out-Null } catch { }
    }
}
