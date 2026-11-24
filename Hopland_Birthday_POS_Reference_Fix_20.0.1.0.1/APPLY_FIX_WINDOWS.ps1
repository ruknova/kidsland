param(
    [string]$ProjectRoot = 'C:\Users\Hamza\Desktop\Z\HopLand'
)
$ErrorActionPreference = 'Stop'
$Database = 'hopland_demo_v2'
$community = Join-Path $ProjectRoot 'community'
$python = Join-Path $community '.venv_hopland\Scripts\python.exe'
$odoo = Join-Path $community 'odoo-bin'
$config = Join-Path $community 'hopland.conf'
$target = Join-Path $ProjectRoot 'custom_addons\hopland_birthday_pos'
$source = Join-Path $PSScriptRoot 'hopland_birthday_pos'
$changed = @('__manifest__.py', 'models\booking.py', 'data\sequence.xml',
    'migrations\20.0.1.0.1\post-booking-sequence.py', 'tests\test_booking.py')
foreach ($required in @($python, $odoo, $config, $target)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path not found: $required" }
}
foreach ($relative in $changed) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $relative))) { throw "Missing patch file: $relative" }
}
# The user's Odoo listens on 127.0.0.1:8070. Refuse to update while it is running.
$client = New-Object System.Net.Sockets.TcpClient
$running = $false
try { $client.Connect('127.0.0.1', 8070); $running = $true } catch { } finally { $client.Dispose() }
if ($running) { throw 'Stop Odoo with Ctrl+C in its running PowerShell window, then run this script again.' }
$manifest = [System.IO.File]::ReadAllText((Join-Path $target '__manifest__.py'))
if ($manifest -notmatch "'version'\s*:\s*'20\.0\.1\.0\.[01]'") {
    throw 'This patch expects add-on version 20.0.1.0.0 or 20.0.1.0.1. No files changed.'
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$backup = Join-Path $ProjectRoot ("birthday_addon_backups\before_reference_fix_" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item -LiteralPath $target -Destination $backup -Recurse
Write-Host "Add-on backup: $backup"
foreach ($relative in $changed) {
    $destination = Join-Path $target $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $source $relative) -Destination $destination -Force
}
$log = Join-Path $PSScriptRoot ("upgrade_" + $stamp + '.log')
Write-Host "Updating birthday add-on on $Database ..."
Push-Location $community
try {
    & $python $odoo -c $config -d $Database -u hopland_birthday_pos --stop-after-init --no-http --logfile $log
    if ($LASTEXITCODE -ne 0) { throw "Module upgrade failed. Keep Odoo stopped and send the log: $log" }
    $verifyLog = Join-Path $PSScriptRoot ("verify_" + $stamp + '.log')
    $verifyCode = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'verify_install.py') -Raw
    $verificationOutput = @($verifyCode | & $python $odoo shell -c $config -d $Database --no-http --shell-interface python --logfile $verifyLog)
    $verificationExit = $LASTEXITCODE
    $verificationOutput | ForEach-Object { Write-Host $_ }
    if ($verificationExit -ne 0 -or ($verificationOutput -join "`n") -notmatch 'HOPLAND_REFERENCE_FIX_OK') {
        throw "Verification failed. Send both logs: $log and $verifyLog"
    }
} finally { Pop-Location }
Write-Host ''
Write-Host 'Reference fix installed and configuration verified. No test reservation or payment was created.'
Write-Host 'Restart Odoo, refresh POS with Ctrl+Shift+R, then retry the birthday reservation.'
Write-Host "Upgrade log: $log"
