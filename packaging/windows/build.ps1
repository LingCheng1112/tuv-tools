param(
    [string]$Python = "python",
    [string]$BaseUrl = "http://124.220.92.76:8080",
    [string]$CertPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

$prepareArgs = @("scripts/prepare_packaging_defaults.py", "--base-url", $BaseUrl)
if ($CertPath.Trim()) {
    $prepareArgs += @("--cert", $CertPath)
}

& $Python @prepareArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m PyInstaller packaging/windows/tuv-tools.spec --noconfirm --clean
exit $LASTEXITCODE
