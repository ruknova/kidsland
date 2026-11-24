# Hopland department workflow update — 20.0.1.1.0

Prepared from the uploaded hopland_birthday_pos.zip, including the already tested booking-reference and computed-payment access fixes.

## What this adds

- **Sales → Parties → New reservation**: select branch, reception register, package, room, parent/customer, child/event name, guest counts, date, included services, optional extras and special requests. Calculate the price, then save/send to Reception.
- Sales can reserve when the register is closed. Reception collects payments after opening its POS session. Bookings are routed to the **selected register**, not every register in the branch.
- **Sales → Parties → Reservations and calendar**: view the existing shared booking records, balances and stages across selected permitted companies.
- **POS**: new Sales reservations are checked every 15 seconds while the page is open and connected; a notification opens Bookings & balances. That list refreshes every 15 seconds while open. Opening a register also announces up to ten waiting Sales reservations. Browser reloads can repeat that waiting-reservation reminder. These are in-app notifications, not browser push, SMS or WhatsApp.
- **Purchasing → Party preparation**: a preparation record and activity are created when validated POS receipts first meet the required deposit. It shows the room, date, guests, included services, extras and customer requests. Purchasing records stock checks, updates progress and can start a linked RFQ. Supplier, quantities and purchase products must be chosen in the RFQ; nothing is purchased automatically.
- **Accounting → Party reservations**: read reservation balances and stages; a payment-review activity is assigned when the received amount changes. These activities do not post or validate accounting entries; the native POS session accounting process remains in place.
- Sales and Reception can see preparation progress on the booking. Sales can also use Parties → Preparation progress.
- Special parties use an event name and the same configured packages, minimum guests, duration and deposit rules. Custom extensions/free time remain outside this update.

## User permissions and notification recipients

Use the accounts already created. No new users or passwords are created by this installer.

| User | Needed application groups |
| --- | --- |
| Central Sales | Sales User (Own Documents or All Documents; use All Documents for the centralized demo) |
| Accounting | Accounting Bookkeeper |
| Purchasing | Purchase User; Inventory User for stock and receipts |
| Reception | POS User |

Select the relevant branches in each user's allowed companies and company switcher. New permissions remain limited by the existing company rules. Sales receives only read access to POS configuration for register selection, not cashier permissions.

Purchasing activities go to **all active internal Purchase users allowed in the booking company**, and Accounting activities go to **all active internal Bookkeepers/accounting managers allowed in that company**. Administrators who have those groups can receive tasks too. Set their Odoo timezone to Asia/Riyadh for consistent demo date entry. Activities appear in Odoo's activity notifications and on the relevant record; delivery also follows Odoo's existing notification preferences. At least one permitted user in each department is needed for assignment.

Preparation is created once. Repeated POS sync/list refreshes do not duplicate it. A refund that drops receipts below the deposit requirement puts preparation on hold and triggers an accounting review. Existing RFQs/POs are not automatically cancelled. Historical payments are baselined during upgrade and do not receive new preparation/tasks retroactively.

## Install on Hamza's local demo database

1. Extract the entire ZIP to `C:\Users\Hamza\Desktop\Z\HopLand\Hopland_Department_Update_20.0.1.1.0`.
2. Stop the running Odoo server using **Ctrl+C**. Keep PostgreSQL running.
3. In PowerShell run:

```powershell
cd "C:\Users\Hamza\Desktop\Z\HopLand\Hopland_Department_Update_20.0.1.1.0"
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY_DEPARTMENT_UPDATE.ps1
```

The script expects `community\.venv_hopland\Scripts\python.exe`, `community\odoo-bin`, `community\hopland.conf`, and database `hopland_demo_v2`. Optional parameters: `-ProjectRoot` and `-Database`.

It backs up the existing add-on and creates a PostgreSQL custom-format database dump before copying files. Backup folders are under `birthday_addon_backups\before_departments_<timestamp>`. Credentials are read from hopland.conf and are not printed. PostgreSQL pg_dump must be available via pg_path in the configuration, PATH, or the standard PostgreSQL installation folder. If backup fails, add-on files are not changed. The database dump does not copy the separate filestore; this update does not remove filestore files.

Upgrade dependencies include `sale_management`, `pos_sale` and `purchase_stock`; Sales, Purchase and Inventory should already be installed in this demo. The installer runs the upgrade and a read-only registry check. It does not create test reservations, payments or RFQs.

Wait for **HOPLAND_DEPARTMENTS_UPGRADE_OK**. If an error occurs, keep Odoo stopped and provide the error/log. Do not repeatedly retry payment validation while an upgrade error remains unresolved.

4. Restart Odoo:

```powershell
cd "C:\Users\Hamza\Desktop\Z\HopLand\community"
& ".\.venv_hopland\Scripts\python.exe" ".\odoo-bin" "-c" ".\hopland.conf"
```

5. Refresh the POS with **Ctrl+Shift+R**. Log department users out and back in.
6. Ensure each target branch has an enabled birthday register, same-currency pricelist, package and room. This update does not clone branch configuration.

## Demo acceptance test

Use a new test booking with a free future room slot. Keep separate browser sessions for Sales, Reception, Accounting and Purchasing.

1. **Sales**: Parties → New reservation; Al Yasmin / its reception register; an existing sample parent; a distinct child/event name; 10 children; package plus cake/photographer. Click Calculate price. With the tested products and no discount, expected total is 1,440 SAR and required deposit 720 SAR.
2. Save/send to Reception. Verify exactly one tentative booking and matching sale reference. No preparation or payment-review activity should exist yet.
3. **Reception**: open the selected register. Within 15 seconds, verify the notification. Use its button to open Bookings & balances; the same reference must appear. Another register must not receive it.
4. Validate the 720 SAR demo deposit in POS. The booking should be Confirmed. Check Accounting's activity notification and Purchasing → Party preparation for the same reference.
5. **Purchasing**: inspect requirements; add a stock-check note; set Preparing. Optionally open a linked RFQ, choose supplier/items for a missing product, and save a draft. Do not send it to a real supplier during the demo.
6. **Sales/Reception**: reopen the booking and verify preparation progress.
7. Complete the 720 SAR balance payment. Accounting gets another review activity; Purchasing still has only one preparation record. The reservation shows 1,440 received, zero balance, Fully Paid.
8. Refresh/reopen repeatedly: no duplicated preparation or payment-review activity for an unchanged received amount.
9. Repeat branch visibility checks as a restricted user; attempt a mismatched branch/register and verify rejection. The centralized users can see only their selected authorized companies.
10. Close the demo register and inspect posting/reconciliation as in the earlier test.

## Validation performed here and remaining checks

Passed here:
- Python syntax for all module files, JavaScript syntax, XML data against Odoo 20's official import schema, local view-inheritance XPath checks, access-file IDs/operations and no direct booking write grants.
- 12 executable Python tests of actual methods using lightweight ORM substitutes: sales authorization, company checks, enabled register, closed-register creation path, shared validator routing, timezone conversion, idempotent handoff, final-payment notifications, refund holds, and the Calculate price action with its five-value pricing result.
- Executable JavaScript checks: correct register, initial/polled arrival notifications, action link, 15-second interval, retry cursor, duplicate suppression for unchanged polls, and offline pause.
- Existing native POS checkout/payment implementation and earlier fixes retained.

**Not executed here:** full Odoo database integration tests, real browser rendering, Windows PowerShell installer, PostgreSQL backup/upgrade, and end-to-end payments. This environment has no running Odoo/PostgreSQL installation. The supplied `tests/test_departments.py` extends the existing Odoo integration tests. Run them only in a disposable test database using `--test-enable --test-tags /hopland_birthday_pos --stop-after-init`, not on the client demo database. The installer registry check is not a replacement for the acceptance test above.

## Recovery

The installer prints the backup path and upgrade logs. An add-on downgrade alone does not reverse database changes. For a complete rollback, stop Odoo, restore the backed-up module and PostgreSQL dump together using the appropriate PostgreSQL restore procedure. Retain the existing filestore. No automatic rollback or database replacement is performed by this package.

Price-action correction (22 November 2026): the wizard reads only the quotation from the five-value helper result and preserves the translation function. Existing installations need only the sales_wizard.py line correction and an Odoo restart; no database upgrade is required for this correction.
