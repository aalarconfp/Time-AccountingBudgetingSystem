# FILE: scripts/run_integration_human_review.ps1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StartDate,

    [Parameter(Mandatory = $true)]
    [string]$EndDate
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\python.exe"

$Script = Join-Path `
    $ProjectRoot `
    "integration_human_review.py"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

if (-not (Test-Path $Script)) {
    throw "Human review script not found: $Script"
}

Write-Host ""
Write-Host "=== Habit Human Review ==="
Write-Host "Dates : $StartDate -> $EndDate"
Write-Host ""

& $Python $Script `
    --start-date $StartDate `
    --end-date $EndDate

if ($LASTEXITCODE -ne 0) {
    throw (
        "Habit human review failed with exit code "
        + $LASTEXITCODE
    )
}

