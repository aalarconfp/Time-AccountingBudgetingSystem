# FILE: scripts/setup_machine.ps1

[CmdletBinding()]
param(
    [ValidateSet("auto", "laptop", "desktop")]
    [string]$Machine = "auto",

    [switch]$RecreateVenv,

    [switch]$SkipOpenAITest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$PythonPath = "C:\ProgramData\anaconda3\python.exe"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "=== $Message ==="
}

function Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Get-ExpectedMachine {
    if ($Machine -ne "auto") {
        return $Machine
    }

    $hostname = $env:COMPUTERNAME

    if ($hostname -eq "AsusLaptop-Andres") {
        return "laptop"
    }

    if ($hostname -eq "DesktopPC-Andres") {
        return "desktop"
    }

    Write-Host "Unable to identify machine automatically."
    Write-Host "Hostname detected: $hostname"
    Write-Host ""
    Write-Host "Run explicitly with:"
    Write-Host "  .\scripts\setup_machine.ps1 -Machine laptop"
    Write-Host "or:"
    Write-Host "  .\scripts\setup_machine.ps1 -Machine desktop"
    exit 1
}

function Test-FileExists {
    param(
        [string]$Path,
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "$Description not found: $Path"
    }
}

function Invoke-VenvPython {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    & $VenvPython @Arguments

    if ($LASTEXITCODE -ne 0) {
        Fail "Python command failed with exit code $LASTEXITCODE."
    }
}

function Test-PythonModule {
    param(
        [string]$Module,
        [string]$Label
    )

    & $VenvPython -c "import $Module; print('${Label}: OK')"

    if ($LASTEXITCODE -ne 0) {
        Fail "$Label validation failed."
    }
}

function Test-ExpectedLauncher {
    param([string]$MachineName)

    $launcher = if ($MachineName -eq "laptop") {
        Join-Path $ProjectRoot "activitywatch_laptop.py"
    }
    else {
        Join-Path $ProjectRoot "activitywatch_desktop.py"
    }

    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        Fail "Expected ActivityWatch launcher is missing: $launcher"
    }

    Write-Host "Launcher      : $launcher"
}

Write-Step "System Tracker Machine Setup"

$DetectedMachine = Get-ExpectedMachine
$Hostname = $env:COMPUTERNAME

Write-Host "Project root  : $ProjectRoot"
Write-Host "Machine       : $DetectedMachine"
Write-Host "Hostname      : $Hostname"
Write-Host "Base Python   : $PythonPath"
Write-Host "Venv          : $VenvPath"

Test-FileExists -Path $PythonPath -Description "Anaconda Python"
Test-FileExists -Path $RequirementsPath -Description "requirements.txt"

Write-Step "Base Python"

$BaseVersion = & $PythonPath --version 2>&1

if ($LASTEXITCODE -ne 0) {
    Fail "Unable to execute Anaconda Python."
}

Write-Host "Base Python   : $BaseVersion"

if ($BaseVersion -notmatch "Python 3\.13\.") {
    Fail "Expected Python 3.13.x but found: $BaseVersion"
}

Write-Step "Virtual Environment"

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

if ($RecreateVenv -and (Test-Path -LiteralPath $VenvPath)) {
    Write-Host "Removing existing .venv..."
    Remove-Item -LiteralPath $VenvPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host "Creating local .venv..."
    & $PythonPath -m venv $VenvPath

    if ($LASTEXITCODE -ne 0) {
        Fail "Failed to create .venv."
    }
}

Test-FileExists -Path $VenvPython -Description "Virtual environment Python"

Write-Host "Venv Python   : $VenvPython"

Write-Step "Dependency Installation"

& $VenvPython -m pip install --upgrade pip

if ($LASTEXITCODE -ne 0) {
    Fail "Failed to upgrade pip."
}

& $VenvPython -m pip install -r $RequirementsPath

if ($LASTEXITCODE -ne 0) {
    Fail "Failed to install requirements.txt."
}

Write-Step "Environment Validation"

Invoke-VenvPython @(
    "--version"
)

Invoke-VenvPython @(
    "-c",
    "import sys; print('Python executable:', sys.executable)"
)

Test-PythonModule -Module "aw_client" -Label "ActivityWatch client"
Test-PythonModule -Module "openai" -Label "OpenAI client"

& $VenvPython -c "from zoneinfo import ZoneInfo; print('Timezone America/Bogota:', ZoneInfo('America/Bogota'))"

if ($LASTEXITCODE -ne 0) {
    Fail "Timezone validation failed."
}

Write-Step "OpenAI Environment"

$ApiKeyPresent = [bool]$env:OPENAI_API_KEY

if ($ApiKeyPresent) {
    Write-Host "OPENAI_API_KEY: SET"
}
else {
    Write-Host "OPENAI_API_KEY: MISSING" -ForegroundColor Yellow
}

if (-not $SkipOpenAITest) {
    if (-not $ApiKeyPresent) {
        Write-Host "Skipping OpenAI API connectivity test because OPENAI_API_KEY is missing." -ForegroundColor Yellow
    }
    else {
        & $VenvPython -c "from openai import OpenAI; client=OpenAI(); response=client.models.list(); print('OpenAI API: OK'); print('Models available:', len(response.data))"

        if ($LASTEXITCODE -ne 0) {
            Fail "OpenAI API connectivity test failed."
        }
    }
}

Write-Step "Machine Configuration"

switch ($DetectedMachine) {
    "laptop" {
        Write-Host "Source        : asus_laptop"
        Write-Host "Device        : AsusLaptop-Andres"
        Write-Host "Context       : Work"
        Write-Host "Launcher      : activitywatch_laptop.py"
    }

    "desktop" {
        Write-Host "Source        : desktop"
        Write-Host "Device        : DesktopPC-Andres"
        Write-Host "Context       : Personal"
        Write-Host "Launcher      : activitywatch_desktop.py"
    }
}

Test-ExpectedLauncher -MachineName $DetectedMachine

Write-Step "ActivityWatch Launcher"

$LauncherPath = if ($DetectedMachine -eq "laptop") {
    Join-Path $ProjectRoot "activitywatch_laptop.py"
}
else {
    Join-Path $ProjectRoot "activitywatch_desktop.py"
}

& $VenvPython $LauncherPath --help

if ($LASTEXITCODE -ne 0) {
    Fail "ActivityWatch launcher validation failed."
}

Write-Step "Environment Ready"

Write-Host "Machine       : $DetectedMachine"
Write-Host "Hostname      : $Hostname"
Write-Host "Python        : $VenvPython"
Write-Host "Dependencies  : OK"
Write-Host "Timezone      : OK"
Write-Host "Launcher      : OK"

if ($ApiKeyPresent) {
    Write-Host "OpenAI        : OK"
}
else {
    Write-Host "OpenAI        : NOT CONFIGURED" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "SYSTEM TRACKER ENVIRONMENT: READY" -ForegroundColor Green