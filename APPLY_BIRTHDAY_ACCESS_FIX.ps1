$ErrorActionPreference = 'Stop'

$projectRoot = 'C:\Users\Hamza\Desktop\Z\HopLand'
$filePath = Join-Path $projectRoot 'custom_addons\hopland_birthday_pos\models\booking.py'
$pythonPath = Join-Path $projectRoot 'community\.venv_hopland\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $filePath)) {
    throw "Booking file not found: $filePath"
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python not found: $pythonPath"
}

# Check that Odoo is stopped.
$client = New-Object System.Net.Sockets.TcpClient
$running = $false

try {
    $client.Connect('127.0.0.1', 8070)
    $running = $true
} catch {
} finally {
    $client.Dispose()
}

if ($running) {
    throw 'Stop Odoo with Ctrl+C, then run this script again.'
}

$content = [System.IO.File]::ReadAllText($filePath)

$oldSelf = 'self._compute_payment()'
$oldBooking = 'booking._compute_payment()'

$newSelf = "self.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])"
$newBooking = "booking.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])"

$selfCount = [regex]::Matches(
    $content, [regex]::Escape($oldSelf)
).Count

$bookingCount = [regex]::Matches(
    $content, [regex]::Escape($oldBooking)
).Count

if (
    $selfCount -eq 0 -and
    $bookingCount -eq 0 -and
    $content.Contains($newSelf) -and
    $content.Contains($newBooking)
) {
    Write-Host 'The fix is already applied. Restart Odoo.'
    exit 0
}

if ($selfCount -ne 1 -or $bookingCount -ne 4) {
    throw "Unexpected code version. No changes made. Found $selfCount summary calls and $bookingCount booking calls."
}

$updated = $content.Replace($oldSelf, $newSelf).Replace(
    $oldBooking, $newBooking
)

$tempFile = [System.IO.Path]::GetTempFileName()

try {
    [System.IO.File]::WriteAllText(
        $tempFile,
        $updated,
        [System.Text.UTF8Encoding]::new($false)
    )

    # Validate the updated Python before changing the installed file.
    & $pythonPath -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_bytes())' $tempFile

    if ($LASTEXITCODE -ne 0) {
        throw 'Python syntax check failed. Installed file was not changed.'
    }

    $backupFolder = Join-Path $projectRoot (
        'birthday_addon_backups\before_access_fix_' +
        (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
    )

    New-Item -ItemType Directory -Path $backupFolder -Force |
        Out-Null

    Copy-Item -LiteralPath $filePath `
        -Destination (Join-Path $backupFolder 'booking.py')

    [System.IO.File]::WriteAllText(
        $filePath,
        $updated,
        [System.Text.UTF8Encoding]::new($false)
    )
} finally {
    Remove-Item -LiteralPath $tempFile -ErrorAction SilentlyContinue
}

Write-Host "Backup: $backupFolder"
Write-Host 'HOPLAND_ACCESS_FIX_OK'
Write-Host 'Corrected 5 compute calls. Python syntax verified.'
Write-Host 'Restart Odoo, refresh POS, and resume the saved booking.'