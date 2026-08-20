# FILE: scripts/run_integration_preliminary.ps1
param(
    [Parameter(Mandatory = $true)]
    [string]$StartDate,

    [Parameter(Mandatory = $true)]
    [string]$EndDate,

    [double]$UnaccountedTargetHours = 3.0
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$AnalysisDir = Join-Path $ProjectRoot "output\Integrated\Analysis"
$Range = "${StartDate}_${EndDate}"
$Archive = Join-Path $AnalysisDir "Preliminary\$Range"
$IntegratedArchive = Join-Path $Archive "Integrated"

Write-Host "=== Integration Preliminary Analysis ==="
Write-Host "Project : $ProjectRoot"
Write-Host "Dates   : $StartDate -> $EndDate"
Write-Host ""

& $Python (Join-Path $ProjectRoot "integration_analysis.py") `
    --start-date $StartDate `
    --end-date $EndDate `
    --unaccounted-target-hours $UnaccountedTargetHours

if ($LASTEXITCODE -ne 0) {
    throw "Integration analysis failed."
}

New-Item -ItemType Directory -Force -Path $Archive | Out-Null
New-Item -ItemType Directory -Force -Path $IntegratedArchive | Out-Null

$analysisFiles = @(
    "Daily_Integration_Analysis.csv",
    "Integration_Analysis_Summary.csv",
    "Integration_Source_80_20.csv",
    "Integration_Category_80_20.csv",
    "Integration_Weekday_Weekend.csv",
    "Integration_Analysis_Report.txt"
)

foreach ($name in $analysisFiles) {
    $source = Join-Path $AnalysisDir $name
    if (-not (Test-Path $source)) {
        throw "Expected analysis output not found: $source"
    }
    Copy-Item $source (Join-Path $Archive $name) -Force
}

$cursor = [datetime]::ParseExact($StartDate, "yyyy-MM-dd", $null)
$end = [datetime]::ParseExact($EndDate, "yyyy-MM-dd", $null)

while ($cursor -le $end) {
    $name = "Integrated_Daily_Time_{0}.csv" -f $cursor.ToString("yyyy-MM-dd")
    $source = Join-Path $AnalysisDir "..\$name"
    $source = [System.IO.Path]::GetFullPath($source)

    if (-not (Test-Path $source)) {
        throw "Expected integrated dataset not found: $source"
    }

    Copy-Item $source (Join-Path $IntegratedArchive $name) -Force
    $cursor = $cursor.AddDays(1)
}

$manifest = Join-Path $Archive "PRELIMINARY_README.txt"
@"
PRELIMINARY INTEGRATION ANALYSIS
Dates: $StartDate -> $EndDate
Target unaccounted time: $UnaccountedTargetHours hours

This directory is an immutable review snapshot.
Review this result before applying Habit manual adjustments.
The Integrated subdirectory preserves the integrated daily inputs used by the review.

Workflow:
1. Review the preliminary analysis.
2. Generate/edit input\Integrated\Habit_Manual_Adjustments.csv.
3. Apply Habit adjustments.
4. Rebuild Integrated Daily Time.
5. Run final analysis.
"@ | Set-Content -Path $manifest -Encoding UTF8

Write-Host ""
Write-Host "Preliminary snapshot saved:"
Write-Host "  $Archive"
Write-Host ""
Write-Host "RESULT: PRELIMINARY INTEGRATION SNAPSHOT PASSED."
