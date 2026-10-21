# Requires an existing native Windows x64 Python >= 3.11. No runtime or pip downloads.
$ErrorActionPreference = 'Stop'
$installer = Join-Path -Path $PSScriptRoot -ChildPath 'mrh_windows_setup.py'
$probe = 'import os,platform,sys; raise SystemExit(0 if os.name == "nt" and platform.machine().lower() in ("amd64","x86_64") and sys.maxsize > 2**32 and sys.version_info >= (3,11) else 1)'
$pythonCommand = $null
$pythonPrefix = @()
foreach ($candidate in @('python.exe', 'py.exe')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $found) { continue }
    $candidatePrefix = @()
    if ($candidate -eq 'py.exe') { $candidatePrefix = @('-3') }
    try {
        & $found.Source @candidatePrefix -I -B -c $probe 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $found.Source
            $pythonPrefix = $candidatePrefix
            break
        }
    } catch { continue }
}
if ($null -eq $pythonCommand) {
    Write-Error 'Install native Windows x64 Python 3.11 or newer from python.org, include its LICENSE.txt, then rerun setup.ps1. WSL and 32-bit Python are unsupported.'
    exit 2
}
& $pythonCommand @pythonPrefix -I -B -X utf8 $installer @args
exit $LASTEXITCODE
