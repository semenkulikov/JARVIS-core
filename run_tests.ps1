param([string]$Python = '')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
if(-not $Python){$Python=Join-Path $root '.venv\Scripts\python.exe'}
if(-not (Test-Path $Python)){throw 'Use -Python with a Python environment containing requirements-test.txt'}
$oldPlugin=$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
$oldBytecode=$env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
    $env:PYTHONDONTWRITEBYTECODE='1'
    & $Python -m pytest (Join-Path $root 'tests') -c (Join-Path $root 'pytest.ini') -q --tb=short
    if($LASTEXITCODE -ne 0){throw "Silent pytest failed (exit $LASTEXITCODE)"}
} finally {
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD=$oldPlugin
    $env:PYTHONDONTWRITEBYTECODE=$oldBytecode
}
Write-Output 'SILENT TESTS PASS: no real audio, models, network or desktop actions.'
