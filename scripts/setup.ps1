[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$WindowsTools = Join-Path $PSScriptRoot 'windows-tools.ps1'
. $WindowsTools

function Get-SetupRequiredCommand {
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

function Invoke-SetupCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Assert-SetupNodeVersion {
    param([Parameter(Mandatory = $true)][string]$NodePath)

    $versionText = (& $NodePath --version | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^v(?<Major>\d+)') {
        throw 'Could not determine the Node.js version. Install Node.js 20 or newer from: https://nodejs.org/en/download'
    }
    if ([int]$Matches.Major -lt 20) {
        throw "Node.js 20 or newer is required; found $versionText. Update it from: https://nodejs.org/en/download"
    }
}

try {
    $uv = Get-SetupRequiredCommand `
        -Name 'uv' `
        -Description 'uv (Python environment manager)' `
        -InstallUrl 'https://docs.astral.sh/uv/getting-started/installation/'
    $node = Get-SetupRequiredCommand `
        -Name 'node' `
        -Description 'Node.js 20 or newer' `
        -InstallUrl 'https://nodejs.org/en/download'
    $npm = Get-SetupRequiredCommand `
        -Name 'npm.cmd' `
        -Description 'npm (included with Node.js)' `
        -InstallUrl 'https://nodejs.org/en/download'
    Assert-SetupNodeVersion -NodePath $node.Source

    Install-PlayTrackFfmpeg -RepoRoot $RepoRoot

    Write-Host 'Installing Python 3.12 with uv...'
    Invoke-SetupCommand `
        -FilePath $uv.Source `
        -Arguments @('python', 'install', '3.12') `
        -FailureMessage 'uv python install failed'

    Write-Host 'Synchronizing backend dependencies...'
    Invoke-SetupCommand `
        -FilePath $uv.Source `
        -Arguments @('sync', '--project', $BackendDir, '--python', '3.12', '--extra', 'dev') `
        -FailureMessage 'uv sync failed'

    Write-Host 'Installing frontend dependencies...'
    Invoke-SetupCommand `
        -FilePath $npm.Source `
        -Arguments @('ci', '--prefix', $FrontendDir) `
        -FailureMessage 'npm ci failed'

    $backendPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
    $fetchModels = Join-Path $PSScriptRoot 'fetch_models.py'
    Write-Host 'Fetching the SAM 2.1 base-plus checkpoint when needed...'
    Invoke-SetupCommand `
        -FilePath $backendPython `
        -Arguments @($fetchModels) `
        -FailureMessage 'Model download failed'

    Set-PlayTrackVideoToolEnvironment -RepoRoot $RepoRoot
    Write-Host 'PlayTrack setup is complete.' -ForegroundColor Green
    Write-Host 'Start the app with: powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1'
    Write-Host 'Start development mode with: powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1'
}
catch {
    Write-Host "PlayTrack setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
