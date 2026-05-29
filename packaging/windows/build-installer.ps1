param(
    [string]$PythonExe = "D:\Anaconda_envs\envs\build_env\python.exe",
    [string]$BaseUrl = "http://124.220.92.76:8080",
    [string]$CertPath = "",
    [string]$InnoCompilerPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Resolve-InnoCompiler {
    param([string]$PreferredPath)

    $candidates = @()
    if ($PreferredPath.Trim()) {
        $candidates += $PreferredPath
    }
    $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($command) {
        $candidates += $command.Source
    }
    $candidates += @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }
    throw "Inno Setup compiler not found. Install Inno Setup 6 or pass -InnoCompilerPath."
}

function Invoke-Step {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($ArgumentList -join ' ')"
    }
}

$python = (Resolve-Path $PythonExe).Path
$innoCompiler = Resolve-InnoCompiler -PreferredPath $InnoCompilerPath
$distAppDir = Join-Path $RepoRoot "dist\TUV-Project-Document-Tool"
$distInstallerDir = Join-Path $RepoRoot "dist\installer"
$buildDir = Join-Path $RepoRoot "build"

if (Test-Path $buildDir) {
    Remove-Item -LiteralPath $buildDir -Recurse -Force
}
if (Test-Path $distAppDir) {
    Remove-Item -LiteralPath $distAppDir -Recurse -Force
}
if (Test-Path $distInstallerDir) {
    Remove-Item -LiteralPath $distInstallerDir -Recurse -Force
}

$prepareArgs = @("scripts/prepare_packaging_defaults.py", "--base-url", $BaseUrl)
if ($CertPath.Trim()) {
    $prepareArgs += @("--cert", $CertPath)
}
Invoke-Step -FilePath $python -ArgumentList $prepareArgs
Invoke-Step -FilePath $python -ArgumentList @("-m", "PyInstaller", "packaging/windows/tuv-tools.spec", "--noconfirm", "--clean")

$pyprojectText = Get-Content (Join-Path $RepoRoot "pyproject.toml") -Raw
if ($pyprojectText -notmatch '(?m)^version\s*=\s*"([^"]+)"\s*$') {
    throw "Failed to read version from pyproject.toml."
}
$appVersion = $Matches[1]

Invoke-Step -FilePath $innoCompiler -ArgumentList @(
    "/DAppVersion=$appVersion",
    (Join-Path $RepoRoot "packaging\windows\tuv-tools-installer.iss")
)
