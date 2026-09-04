[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
# PLAYTRACK_HOST=0.0.0.0 exposes the app to the local network (origin/host checks, no authentication).
$BindHost = if ($env:PLAYTRACK_HOST) { $env:PLAYTRACK_HOST } else { '127.0.0.1' }
$BrowseHost = if ($BindHost -eq '0.0.0.0') { '127.0.0.1' } else { $BindHost }
$AppUrl = "http://${BrowseHost}:8000"
$WindowsTools = Join-Path $PSScriptRoot 'windows-tools.ps1'
. $WindowsTools
$backendProcess = $null

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
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "The backend stopped before it became ready (exit code $($Process.ExitCode))."
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
    throw "The backend did not become ready at $Url within $TimeoutSeconds seconds."
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
    Set-PlayTrackVideoToolEnvironment -RepoRoot $RepoRoot

    Write-Host 'Synchronizing backend dependencies...'
    Invoke-NativeCommand `
        -Command $uv `
        -Arguments @(
            'sync', '--project', $BackendDir, '--python', '3.12',
            '--managed-python', '--extra', 'dev', '--locked'
        ) `
        -FailureMessage 'Backend dependency synchronization failed'

    Write-Host 'Building the current frontend...'
    Push-Location $FrontendDir
    try {
        if (Test-NodeModulesStale -FrontendPath $FrontendDir) {
            Write-Host 'Installing frontend dependencies with npm ci...'
            Invoke-NativeCommand `
                -Command $npm `
                -Arguments @('ci') `
                -FailureMessage 'npm ci failed'
        }
        Invoke-NativeCommand `
            -Command $npm `
            -Arguments @('run', 'build') `
            -FailureMessage 'Frontend build failed'
    }
    finally {
        Pop-Location
    }

    Write-Host "Starting PlayTrack at $AppUrl ..."
    $backendProcess = Start-Process `
        -FilePath $uv.Source `
        -ArgumentList @('run', '--no-sync', 'uvicorn', 'app.main:app', '--host', $BindHost, '--port', '8000') `
        -WorkingDirectory $BackendDir `
        -PassThru `
        -NoNewWindow

    Wait-ForHttp -Url "$AppUrl/api/health" -Process $backendProcess
    Write-Host 'PlayTrack is ready. Opening your default browser.'
    Start-Process $AppUrl
    Write-Host 'Press Ctrl+C to stop PlayTrack.'

    Wait-Process -Id $backendProcess.Id
    $backendProcess.Refresh()
    if ($backendProcess.ExitCode -ne 0) {
        throw "The backend exited with code $($backendProcess.ExitCode)."
    }
}
catch {
    Write-Host "PlayTrack could not start: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Stop-ProcessTree -Process $backendProcess
}
