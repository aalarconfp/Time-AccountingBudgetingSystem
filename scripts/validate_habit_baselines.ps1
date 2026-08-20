# FILE: scripts/validate_habit_baselines.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BaselineFile = Join-Path `
    $ProjectRoot `
    "input\Integrated\Habit_Initial_Baselines.csv"

$AllowedCategories = @(
    "Family Time Tracking",
    "Social Time Tracking",
    "TV Time tracking",
    "Personal Time Tracking",
    "Console Time Tracking"
)

if (-not (Test-Path $BaselineFile)) {
    throw "Missing baseline file: $BaselineFile"
}

$Rows = @(Import-Csv $BaselineFile)

if ($Rows.Count -eq 0) {
    throw "Baseline file is empty: $BaselineFile"
}

$RequiredColumns = @(
    "Date",
    "Category",
    "Duration_sec",
    "Reason"
)

$Columns = @(
    $Rows[0].PSObject.Properties.Name
)

foreach ($Column in $RequiredColumns) {
    if ($Column -notin $Columns) {
        throw "Missing required column '$Column'."
    }
}

$Seen = @{}

foreach ($Row in $Rows) {
    try {
        $ParsedDate = [datetime]::ParseExact(
            $Row.Date,
            "yyyy-MM-dd",
            [Globalization.CultureInfo]::InvariantCulture
        )
    }
    catch {
        throw "Invalid Date '$($Row.Date)'. Expected YYYY-MM-DD."
    }

    if ($Row.Category -notin $AllowedCategories) {
        throw "Unsupported baseline category '$($Row.Category)'."
    }

    $Key = "$($Row.Date)|$($Row.Category)"

    if ($Seen.ContainsKey($Key)) {
        throw "Duplicate baseline: $Key"
    }

    $Seen[$Key] = $true

    $Duration = 0.0

    if (-not [double]::TryParse(
        $Row.Duration_sec,
        [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$Duration
    )) {
        throw "Invalid Duration_sec for $Key."
    }

    if ($Duration -lt 0) {
        throw "Negative Duration_sec for $Key."
    }

    if ([string]::IsNullOrWhiteSpace($Row.Reason)) {
        throw "Reason cannot be empty for $Key."
    }
}

Write-Host ""
Write-Host "=== Habit Initial Baseline Validation ==="
Write-Host "File : $BaselineFile"
Write-Host "Rows : $($Rows.Count)"
Write-Host ""

$Rows |
    Format-Table Date,Category,Duration_sec,Reason -AutoSize

Write-Host ""
Write-Host "RESULT: HABIT INITIAL BASELINES VALID."