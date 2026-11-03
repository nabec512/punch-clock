<#
.SYNOPSIS
    Test and package Punch Clock into dist\.
.PARAMETER RequireInstaller
    Fail instead of skipping the installer when Inno Setup is missing. Used by the release workflow.
#>
param(
    [switch]$RequireInstaller
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Command $($Arguments -join ' ')" }
}

function Find-InnoSetup {
    $found = Get-Command iscc -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$versionLine = Select-String -Path 'src\punch_clock\__init__.py' -Pattern '__version__ = "(.+)"'
if (-not $versionLine) { throw 'Could not read __version__ from src\punch_clock\__init__.py' }
$version = $versionLine.Matches[0].Groups[1].Value
Write-Host "Building Punch Clock $version"

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'Creating .venv'
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Checked 'py' @('-3.12', '-m', 'venv', '.venv')
    }
    else {
        Invoke-Checked 'python' @('-m', 'venv', '.venv')
    }
}
Invoke-Checked $python @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '-r', 'packaging\requirements.txt')

Write-Host 'Running tests'
Invoke-Checked $python @('-m', 'pytest', '--quiet')

foreach ($folder in 'build', 'dist') {
    if (Test-Path $folder) { Remove-Item $folder -Recurse -Force }
}

Write-Host 'Packaging the app'
Invoke-Checked $python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
    '--distpath', 'dist', '--workpath', 'build', 'packaging\punch_clock.spec')

Write-Host 'Trying the packaged app on a sample export'
$smoke = Join-Path 'build' 'smoke'
New-Item -ItemType Directory -Path $smoke -Force | Out-Null
$sample = Join-Path $smoke 'sample.xlsx'
Invoke-Checked $python @('tests\sample_export.py', $sample)
$app = Start-Process -FilePath 'dist\PunchClock\PunchClock.exe' -ArgumentList "`"$sample`"", '--output-dir', "`"$smoke`"" -Wait -PassThru
if ($app.ExitCode -ne 0) { throw "The packaged app exited with code $($app.ExitCode)." }
$week = Get-ChildItem $smoke -Directory | Select-Object -First 1
if (-not $week) { throw 'The packaged app did not create the output folder.' }
if (-not (Get-ChildItem (Join-Path $week.FullName 'Supervisor files') -Filter '*Printable.pdf')) { throw 'The packaged app did not create the PDFs.' }
if (-not (Get-ChildItem (Join-Path $week.FullName 'Supervisor files') -Filter '*.xlsx')) { throw 'The packaged app did not create the review files.' }
$app = Start-Process -FilePath 'dist\PunchClock\PunchClock.exe' -ArgumentList '--approve', "`"$($week.FullName)`"" -Wait -PassThru
if ($app.ExitCode -ne 0) { throw "The packaged app exited with code $($app.ExitCode) when building the approved report." }
if (-not (Get-ChildItem $week.FullName -Filter 'Provisional timesheets*.pdf')) { throw 'The packaged app did not create the provisional report.' }

$archive = "dist\PunchClock-$version-windows.zip"
# Antivirus can hold the app's files briefly just after the smoke test has run them.
foreach ($attempt in 1..6) {
    try {
        Compress-Archive -Path 'dist\PunchClock' -DestinationPath $archive -Force
        break
    }
    catch {
        if ($attempt -eq 6) { throw }
        Write-Host 'The app files are busy; trying again shortly.'
        Start-Sleep -Seconds 5
    }
}

$iscc = Find-InnoSetup
if ($iscc) {
    Write-Host 'Building the installer'
    Invoke-Checked $iscc @('/Q', "/DAppVersion=$version", 'packaging\installer.iss')
}
elseif ($RequireInstaller) {
    throw 'Inno Setup 6 is required for a release but was not found.'
}
else {
    Write-Warning 'Inno Setup 6 not found, so no installer was built. The zip is still usable.'
}

$files = Get-ChildItem 'dist' -File | Where-Object { $_.Extension -in '.zip', '.exe' }
$files | ForEach-Object {
    "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)"
} | Set-Content 'dist\SHA256SUMS.txt' -Encoding ascii

Write-Host ''
Write-Host "Done. In dist\:"
Get-ChildItem 'dist' | ForEach-Object { Write-Host "  $($_.Name)" }
