# Hopland Birthday POS — booking reference fix 20.0.1.0.1

This update addresses the required Name error when creating a birthday reservation.

## Cause and correction

The old sequence XML omitted company_id, letting Odoo assign the installation
company. The reservation code looked up that sequence using the active company,
not explicitly the register company, and passed a failed lookup into the required
booking name. The precise company assignment in the user's database was not
available for inspection here.

- Make the module-owned default sequence shared across companies.
- Migrate the existing noupdate sequence in place; preserve ID, prefix, padding,
  existing references and the next-number counter.
- Look up references under the register company. Separately configured company
  sequences retain their normal priority.
- Raise a clear configuration error if no sequence can be found, before creating
  the linked sales order. No dummy names or reset numbering.
- Include three Odoo regression tests for company selection, missing sequences,
  and matching booking/sales references.

The supplied source includes the user's earlier stylesheet and template fixes.
The update script copies only the five files changed by this patch; it leaves
installed UI files, pricing settings, orders and payment configuration untouched.
Extra-time editing is deferred as requested.

## Apply on Windows

Target: hopland_demo_v2 only. Odoo project: C:\Users\Hamza\Desktop\Z\HopLand.
A database backup is recommended before any module upgrade.

1. Extract this ZIP to a new folder.
2. Stop the running Odoo server with Ctrl+C. Keep its console open.
3. Open PowerShell in the extracted folder containing APPLY_FIX_WINDOWS.ps1.
4. Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY_FIX_WINDOWS.ps1
```

The script backs up the existing add-on, updates the module (including its
migration), and verifies the version and sequence without consuming a reference.
Wait for `HOPLAND_REFERENCE_FIX_OK`. If the command fails, keep the logs and send
them for review. Do not uninstall the module or reset its sequence counter.

5. Restart Odoo:

```powershell
cd "C:\Users\Hamza\Desktop\Z\HopLand\community"
& ".\.venv_hopland\Scripts\python.exe" ".\odoo-bin" "-c" ".\hopland.conf"
```

6. Refresh POS with Ctrl+Shift+R. Open Birthdays and check Bookings & balances
   before creating a new test reservation. Resume an existing test if present.
7. Use a future available slot, 10 children, cake and photographer, 0% discount.
   Expected total: 1,440 SAR; deposit: 720 SAR; balance: 720 SAR.
8. Select 50% deposit and Reserve & take payment. Verify the POS asks for 720 SAR
   before validating. If an error appears, capture it, including the header area.

## Validation and limits

See VALIDATION.txt for checks actually run. The full Odoo runtime/database and
Windows PowerShell are not installed in the build workspace. The Odoo integration
suite and Windows installer therefore require verification on the target system.
The complete reservation/payment workflow has not yet passed acceptance testing.

## Recovery

The code backup is printed by the installer under birthday_addon_backups.
The migration only removes the company restriction from the module-owned default
sequence and never resets counters. Review logs before restoring code; restoring
a code folder does not restore database state. Database restore is a separate
operation. Do not run integration tests against the demonstration database with
existing transactions; use a disposable copy.
