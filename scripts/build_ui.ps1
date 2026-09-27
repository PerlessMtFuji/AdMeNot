# Buduje UI (Svelte) do src/demalware/app/web. Użycie: powershell -ExecutionPolicy Bypass -File scripts/build_ui.ps1
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..\ui")
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "UI tests failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "UI build failed" }
    Write-Host "UI zbudowane: src\demalware\app\web"
} finally {
    Pop-Location
}
