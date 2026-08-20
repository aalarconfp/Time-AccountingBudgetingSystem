# FILE: scripts/apply_habit_manual_adjustments.ps1
param(
    [Parameter(Mandatory = $true)]
    [string]$StartDate,

    [Parameter(Mandatory = $true)]
    [string]$EndDate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$AdjustmentFile = Join-Path `
    $ProjectRoot `
    "input\Integrated\Habit_Manual_Adjustments.csv"

if (-not (Test-Path $AdjustmentFile)) {
    throw "Adjustment CSV not found: $AdjustmentFile"
}

Write-Host "=== Apply Habit Manual Adjustments ==="
Write-Host "Dates      : $StartDate -> $EndDate"
Write-Host "Adjustment : $AdjustmentFile"
Write-Host ""

& $Python (Join-Path $ProjectRoot "habit_manual_adjustments.py") `
    --start-date $StartDate `
    --end-date $EndDate `
    --adjustment-file $AdjustmentFile

if ($LASTEXITCODE -ne 0) {
    throw "Habit manual adjustments failed."
}

Write-Host ""
Write-Host "Do not rerun habit_offdevice_builder.py after this step."
Write-Host "Next step: rebuild Integrated Daily Time."
Write-Host ""
Write-Host "RESULT: HABIT MANUAL ADJUSTMENTS PASSED."
