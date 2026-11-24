param(
    [string]$ProjectRoot = 'C:\Users\Hamza\Desktop\Z\HopLand',
    [string]$Database = 'hopland_demo_v2'
)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $ProjectRoot 'community\.venv_hopland\Scripts\python.exe'
$odooPath = Join-Path $ProjectRoot 'community\odoo-bin'
$configPath = Join-Path $ProjectRoot 'community\hopland.conf'
$addonPath = Join-Path $ProjectRoot 'custom_addons\hopland_birthday_pos'
$sourcePath = Join-Path $PSScriptRoot 'hopland_birthday_pos'
foreach ($requiredPath in @($pythonPath, $odooPath, $configPath, $addonPath, $sourcePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw "Required path not found: $requiredPath" }
}
$client = New-Object System.Net.Sockets.TcpClient
$running = $false
try { $client.Connect('127.0.0.1', 8070); $running = $true } catch {} finally { $client.Dispose() }
if ($running) { throw 'Stop Odoo with Ctrl+C in its server window, then run this script again.' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$backupPath = Join-Path $ProjectRoot "birthday_addon_backups\before_departments_$stamp"
New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
Copy-Item -LiteralPath $addonPath -Destination (Join-Path $backupPath 'hopland_birthday_pos') -Recurse
$dbBackup = Join-Path $backupPath "$Database.dump"
& $pythonPath (Join-Path $PSScriptRoot 'backup_database.py') $configPath $Database $dbBackup
if ($LASTEXITCODE -ne 0) { throw 'Backup did not complete. Installation stopped before changing the add-on.' }
Write-Host "Backup folder: $backupPath"
Copy-Item -Path (Join-Path $sourcePath '*') -Destination $addonPath -Recurse -Force
$logPath = Join-Path $PSScriptRoot "upgrade_departments_$stamp.log"
Write-Host "Updating birthday departments on $Database ..."
& $pythonPath $odooPath -c $configPath -d $Database -u hopland_birthday_pos --stop-after-init --no-http --logfile $logPath
if ($LASTEXITCODE -ne 0) { throw "Odoo upgrade failed. Keep Odoo stopped and share the error from $logPath" }
$verifyLog = Join-Path $PSScriptRoot "verify_departments_$stamp.log"
Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'verify_upgrade.py') | & $pythonPath $odooPath shell -c $configPath -d $Database --no-http --logfile $verifyLog | Tee-Object -Variable verificationOutput
if ($LASTEXITCODE -ne 0) { throw "Upgrade verification failed. Keep Odoo stopped and share $verifyLog" }
if (($verificationOutput -join "`n") -notmatch 'HOPLAND_DEPARTMENTS_UPGRADE_OK') { throw "Verification marker missing. Share $verifyLog before restarting." }
Write-Host ''
Write-Host 'Restart Odoo, refresh POS with Ctrl+Shift+R, and log the department users out and back in.'
Write-Host "Upgrade log: $logPath"
Write-Host 'Start the new demo in Sales > Parties > New reservation.'
