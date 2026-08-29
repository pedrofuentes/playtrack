$script:PlayTrackFfmpegVersion = '9.0.1'
$script:PlayTrackFfmpegArchiveName = 'ffmpeg-9.0.1-essentials_build.zip'
$script:PlayTrackFfmpegArchiveUrl = "https://www.gyan.dev/ffmpeg/builds/packages/$($script:PlayTrackFfmpegArchiveName)"
$script:PlayTrackFfmpegArchiveSha256 = 'FEC81AE03971D9DD4BE3EBE02E263BD2EC1D789483F931BDBA5F5715E65DA2E9'

function Get-PlayTrackLocalVideoToolPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Name
    )

    return Join-Path $RepoRoot ".tools\ffmpeg\bin\$Name.exe"
}

function Resolve-PlayTrackVideoTool {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [AllowEmptyString()][string]$ConfiguredValue
    )

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredValue)) {
        if (Test-Path -LiteralPath $ConfiguredValue -PathType Leaf) {
            return (Resolve-Path -LiteralPath $ConfiguredValue).Path
        }
        $configuredCommand = Get-Command -Name $ConfiguredValue -ErrorAction SilentlyContinue
        if ($null -ne $configuredCommand) {
            return $configuredCommand.Source
        }
        throw "$EnvironmentName points to '$ConfiguredValue', but that executable was not found."
    }

    $pathCommand = Get-Command -Name $Name -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand) {
        return $pathCommand.Source
    }

    $localPath = Get-PlayTrackLocalVideoToolPath -RepoRoot $RepoRoot -Name $Name
    if (Test-Path -LiteralPath $localPath -PathType Leaf) {
        return (Resolve-Path -LiteralPath $localPath).Path
    }

    return $null
}

function Assert-PlayTrackVideoTool {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path
    )

    & $Path -version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "$Name exists at '$Path' but failed its version check (exit code $LASTEXITCODE)."
    }
}

function Set-PlayTrackVideoToolEnvironment {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $ffmpeg = Resolve-PlayTrackVideoTool `
        -RepoRoot $RepoRoot `
        -Name 'ffmpeg' `
        -EnvironmentName 'PLAYTRACK_FFMPEG' `
        -ConfiguredValue $env:PLAYTRACK_FFMPEG
    $ffprobe = Resolve-PlayTrackVideoTool `
        -RepoRoot $RepoRoot `
        -Name 'ffprobe' `
        -EnvironmentName 'PLAYTRACK_FFPROBE' `
        -ConfiguredValue $env:PLAYTRACK_FFPROBE

    if ($null -eq $ffmpeg -or $null -eq $ffprobe) {
        throw "FFmpeg and ffprobe are required. Run: powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1"
    }

    Assert-PlayTrackVideoTool -Name 'ffmpeg' -Path $ffmpeg
    Assert-PlayTrackVideoTool -Name 'ffprobe' -Path $ffprobe
    $env:PLAYTRACK_FFMPEG = $ffmpeg
    $env:PLAYTRACK_FFPROBE = $ffprobe

    Write-Host "Using FFmpeg: $ffmpeg"
    Write-Host "Using ffprobe: $ffprobe"
}

function Assert-PlayTrackPathWithinRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $resolvedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify '$resolvedPath' because it is outside '$resolvedRoot'."
    }
}

function Install-PlayTrackFfmpeg {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $ffmpeg = Get-PlayTrackLocalVideoToolPath -RepoRoot $RepoRoot -Name 'ffmpeg'
    $ffprobe = Get-PlayTrackLocalVideoToolPath -RepoRoot $RepoRoot -Name 'ffprobe'
    if ((Test-Path -LiteralPath $ffmpeg -PathType Leaf) -and
        (Test-Path -LiteralPath $ffprobe -PathType Leaf)) {
        Assert-PlayTrackVideoTool -Name 'ffmpeg' -Path $ffmpeg
        Assert-PlayTrackVideoTool -Name 'ffprobe' -Path $ffprobe
        Write-Host "Using the existing repo-local FFmpeg $($script:PlayTrackFfmpegVersion)."
        return
    }

    $toolsRoot = Join-Path $RepoRoot '.tools'
    $installRoot = Join-Path $toolsRoot 'ffmpeg'
    $stagingRoot = Join-Path $toolsRoot ".ffmpeg-staging-$PID"
    $archivePath = Join-Path $toolsRoot $script:PlayTrackFfmpegArchiveName

    Assert-PlayTrackPathWithinRoot -Path $toolsRoot -Root $RepoRoot
    Assert-PlayTrackPathWithinRoot -Path $installRoot -Root $RepoRoot
    Assert-PlayTrackPathWithinRoot -Path $stagingRoot -Root $RepoRoot
    Assert-PlayTrackPathWithinRoot -Path $archivePath -Root $RepoRoot

    New-Item -ItemType Directory -Path $toolsRoot -Force | Out-Null
    try {
        Write-Host "Downloading FFmpeg $($script:PlayTrackFfmpegVersion) essentials build..."
        Invoke-WebRequest `
            -Uri $script:PlayTrackFfmpegArchiveUrl `
            -OutFile $archivePath `
            -UseBasicParsing

        $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
        if ($actualHash -ne $script:PlayTrackFfmpegArchiveSha256) {
            throw "FFmpeg archive checksum mismatch. Expected $($script:PlayTrackFfmpegArchiveSha256), got $actualHash."
        }

        New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
        Expand-Archive -LiteralPath $archivePath -DestinationPath $stagingRoot
        $packageRoot = Get-ChildItem -LiteralPath $stagingRoot -Directory |
            Where-Object {
                (Test-Path -LiteralPath (Join-Path $_.FullName 'bin\ffmpeg.exe') -PathType Leaf) -and
                (Test-Path -LiteralPath (Join-Path $_.FullName 'bin\ffprobe.exe') -PathType Leaf)
            } |
            Select-Object -First 1
        if ($null -eq $packageRoot) {
            throw 'The FFmpeg archive did not contain the expected ffmpeg.exe and ffprobe.exe files.'
        }

        if (Test-Path -LiteralPath $installRoot) {
            Remove-Item -LiteralPath $installRoot -Recurse -Force
        }
        Move-Item -LiteralPath $packageRoot.FullName -Destination $installRoot
    }
    finally {
        if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
            Remove-Item -LiteralPath $archivePath -Force
        }
        if (Test-Path -LiteralPath $stagingRoot -PathType Container) {
            Remove-Item -LiteralPath $stagingRoot -Recurse -Force
        }
    }

    Assert-PlayTrackVideoTool -Name 'ffmpeg' -Path $ffmpeg
    Assert-PlayTrackVideoTool -Name 'ffprobe' -Path $ffprobe
    Write-Host "Installed FFmpeg $($script:PlayTrackFfmpegVersion) under $installRoot."
}
