# FILE: scripts/run_integration_final.ps1
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
$Archive = Join-Path $AnalysisDir "Final\$Range"
$IntegratedArchive = Join-Path $Archive "Integrated"

Write-Host "=== Integration Final Build + Analysis ==="
Write-Host "Dates : $StartDate -> $EndDate"
Write-Host ""

& $Python (Join-Path $ProjectRoot "integrated_daily_time_builder.py") `
    --start-date $StartDate `
    --end-date $EndDate

if ($LASTEXITCODE -ne 0) {
    throw "Integrated Daily Time builder failed."
}

& $Python (Join-Path $ProjectRoot "integration_analysis.py") `
    --start-date $StartDate `
    --end-date $EndDate `
    --unaccounted-target-hours $UnaccountedTargetHours

if ($LASTEXITCODE -ne 0) {
    throw "Final integration analysis failed."
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
        throw "Expected final analysis output not found: $source"
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
        throw "Expected final integrated dataset not found: $source"
    }

    Copy-Item $source (Join-Path $IntegratedArchive $name) -Force
    $cursor = $cursor.AddDays(1)
}

Write-Host ""
Write-Host "Final snapshot saved:"
Write-Host "  $Archive"
Write-Host ""
Write-Host "RESULT: FINAL INTEGRATION ANALYSIS PASSED."
