param(
    [string]$CondaEnv = "build_env",
    [string]$BaseUrl = "http://124.220.92.76:8080",
    [string]$CertPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Run-Conda {
    $args = @("run", "-n", $CondaEnv, "python") + $args
    $result = & conda @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw $result }
}

$prepareArgs = @("scripts/prepare_packaging_defaults.py", "--base-url", $BaseUrl)
if ($CertPath.Trim()) {
    $prepareArgs += @("--cert", $CertPath)
}

Run-Conda @prepareArgs
Run-Conda -m PyInstaller packaging/windows/tuv-tools.spec --noconfirm --clean
