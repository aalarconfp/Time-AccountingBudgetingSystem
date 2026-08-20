# FILE: scripts/run_habit_human_review.ps1
param(
    [Parameter(Mandatory = $true)]
    [string]$StartDate,

    [Parameter(Mandatory = $true)]
    [string]$EndDate,

    [switch]$ForceTemplate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Archive = Join-Path `
    $ProjectRoot `
    "output\Integrated\Analysis\Preliminary\${StartDate}_${EndDate}"

if (-not (Test-Path (Join-Path $Archive "Daily_Integration_Analysis.csv"))) {
    throw "Preliminary analysis snapshot not found: $Archive"
}

$args = @(
    (Join-Path $ProjectRoot "integration_human_review.py"),
    "--start-date", $StartDate,
    "--end-date", $EndDate,
    "--preliminary-dir", $Archive
)

if ($ForceTemplate) {
    $args += "--force-template"
}

Write-Host "=== Habit Human-in-the-Loop Review ==="
Write-Host "Dates       : $StartDate -> $EndDate"
Write-Host "Preliminary : $Archive"
Write-Host ""

& $Python @args

if ($LASTEXITCODE -ne 0) {
    throw "Habit human review generation failed."
}

Write-Host ""
Write-Host "Edit this file manually:"
Write-Host "  $ProjectRoot\input\Integrated\Habit_Manual_Adjustments.csv"
Write-Host ""
Write-Host "Adjustment_min:"
Write-Host "  positive = add missed time"
Write-Host "  negative = reduce overstated time"
Write-Host "  zero     = no change"
Write-Host ""
Write-Host "RESULT: HABIT HUMAN REVIEW READY."
