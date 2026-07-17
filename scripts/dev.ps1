[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$BackendUrl = 'http://127.0.0.1:8000'
$FrontendUrl = 'http://127.0.0.1:5173'
$backendProcess = $null
$frontendProcess = $null

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$InstallUrl
    )

    $command = Get-Command -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "$Description is required, but '$Name' was not found on PATH.`nInstall it from: $InstallUrl"
    }
    return $command
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    & $Command.Source @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Assert-NodeVersion {
    param([Parameter(Mandatory = $true)]$Command)

    $versionText = (& $Command.Source --version | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^v(?<Major>\d+)') {
        throw "Could not determine the Node.js version. Install Node.js 20 or newer from: https://nodejs.org/en/download"
    }
    if ([int]$Matches.Major -lt 20) {
        throw "Node.js 20 or newer is required; found $versionText. Update it from: https://nodejs.org/en/download"
    }
}

function Test-NodeModulesStale {
    param([Parameter(Mandatory = $true)][string]$FrontendPath)

    $nodeModules = Join-Path $FrontendPath 'node_modules'
    if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
        return $true
    }
    $packageLock = Join-Path $FrontendPath 'package-lock.json'
    $installedLock = Join-Path $nodeModules '.package-lock.json'
    if ((Test-Path -LiteralPath $packageLock -PathType Leaf) -and
        (-not (Test-Path -LiteralPath $installedLock -PathType Leaf))) {
        return $true
    }
    if ((Test-Path -LiteralPath $packageLock -PathType Leaf) -and
        ((Get-Item $packageLock).LastWriteTimeUtc -gt (Get-Item $installedLock).LastWriteTimeUtc)) {
        return $true
    }
    return $false
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$ProcessName,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "$ProcessName stopped before it became ready (exit code $($Process.ExitCode))."
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    }
    throw "$ProcessName did not become ready at $Url within $TimeoutSeconds seconds."
}

function Stop-ProcessTree {
    param($Process)

    if ($null -eq $Process) {
        return
    }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            & taskkill.exe /PID $Process.Id /T /F *> $null
        }
    }
    catch {
        Write-Warning "Could not stop process tree $($Process.Id): $($_.Exception.Message)"
    }
}

try {
    $uv = Get-RequiredCommand `
        -Name 'uv' `
        -Description 'uv (Python environment manager)' `
        -InstallUrl 'https://docs.astral.sh/uv/getting-started/installation/'
    $node = Get-RequiredCommand `
        -Name 'node' `
        -Description 'Node.js 20 or newer' `
        -InstallUrl 'https://nodejs.org/en/download'
    $npm = Get-RequiredCommand `
        -Name 'npm.cmd' `
        -Description 'npm (included with Node.js)' `
        -InstallUrl 'https://nodejs.org/en/download'
    Assert-NodeVersion -Command $node

    $backendPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
        throw "Backend environment is missing. Run: uv sync --project backend --python 3.12 --extra dev --extra locate"
    }

    if (Test-NodeModulesStale -FrontendPath $FrontendDir) {
        Write-Host 'Installing frontend dependencies with npm ci...'
        Push-Location $FrontendDir
        try {
            Invoke-NativeCommand `
                -Command $npm `
                -Arguments @('ci') `
                -FailureMessage 'npm ci failed'
        }
        finally {
            Pop-Location
        }
    }

    Write-Host 'Starting the FindMe backend and Vite development server...'
    $backendProcess = Start-Process `
        -FilePath $uv.Source `
        -ArgumentList @('run', '--no-sync', '--extra', 'dev', '--extra', 'locate', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $BackendDir `
        -PassThru `
        -NoNewWindow
    $frontendProcess = Start-Process `
        -FilePath $npm.Source `
        -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173') `
        -WorkingDirectory $FrontendDir `
        -PassThru `
        -NoNewWindow

    Wait-ForHttp -Url "$BackendUrl/api/health" -Process $backendProcess -ProcessName 'Backend'
    Wait-ForHttp -Url $FrontendUrl -Process $frontendProcess -ProcessName 'Vite'

    Write-Host "FindMe backend: $BackendUrl"
    Write-Host "FindMe frontend: $FrontendUrl"
    Write-Host 'Press Ctrl+C to stop both development servers.'
    Start-Process $FrontendUrl

    while ($true) {
        $backendProcess.Refresh()
        $frontendProcess.Refresh()
        if ($backendProcess.HasExited) {
            throw "The backend stopped unexpectedly (exit code $($backendProcess.ExitCode))."
        }
        if ($frontendProcess.HasExited) {
            throw "Vite stopped unexpectedly (exit code $($frontendProcess.ExitCode))."
        }
        Start-Sleep -Milliseconds 500
    }
}
catch {
    Write-Host "FindMe development mode stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Stop-ProcessTree -Process $frontendProcess
    Stop-ProcessTree -Process $backendProcess
}
