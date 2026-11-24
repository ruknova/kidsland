# Hopland receipt → Accounting handoff — 20.0.1.2.0

Update for Hamza's existing 20.0.1.1.0 department customization on Odoo 20 / hopland_demo_v2.

## Behavior

When a supplier receipt for a purchase order linked to a party is completed, the system creates:

- A review in **Accounting → Purchase receipts**, with the branch, booking, supplier, PO reference, receipt reference, transfer date, actual items/quantities, and full PO total including tax.
- An activity for each active internal Bookkeeper/accounting manager allowed in that branch. Administrator accounts with those rights receive one too.
- A link to the review from the party reservation form for Accounting and Purchasing.

Accounting can open the review from the activity clock without Purchasing or Inventory access. It contains source references and snapshots; it does not grant general access to purchase orders or receipts. The booking link opens the shared reservation. **Matched bills / credits** displays only existing vendor bills/credits whose lines are matched to this PO and which the accountant may access. An empty list means no matching bill exists; it does not create one. Use the native Accounting supplier-bill matching workflow when the supplier invoice arrives.

After checking the supplier document, the accountant may add review notes and click **Mark reviewed**. This closes this review's generated activities for all recipients and records who reviewed it. It does not post a bill or register payment. Completing an individual activity with Odoo's ordinary Done control does not change the shared review state; use Mark reviewed for the shared queue.

Partial deliveries each have a review for their actual received quantities. The displayed monetary amount is explicitly the **full PO total at receipt**, not an allocated partial-receipt value. Completed supplier returns produce a separate credit-review task. Internal transfers, draft/cancelled receipts, zero quantities and purchases without a party link do not generate reviews. Reprocessing the same transfer does not duplicate the record or already assigned tasks, even after an activity was completed.

No draft bills, credits, journal entries or payments are generated. Existing POS accounting remains native. The cake purchase remains a separate cost from the customer sale. Non-stock services such as photography do not generate a stock receipt and are outside this receipt-triggered handoff.

## Existing receipt and menus

The upgrade catches up completed supplier transfers linked to party purchases, including **YAS/IN/00001 / P00002 / BDAY/2026/00004** in the current demo. It does not validate a new receipt, create another PO, or change any bill. It will include other completed party-linked supplier transfers if they exist.

The administrator's corrected **Party reservations** parent menu is preserved. **Purchase receipts** is placed beside it under the same Accounting root. The Calculate price correction and existing department functionality are included.

## Install

1. Extract the ZIP into:
   `C:\Users\Hamza\Desktop\Z\HopLand\Hopland_Receipt_Handoff_20.0.1.2.0`
   Keep the installer beside the included `hopland_birthday_pos` folder. Do not copy files manually.
2. Stop Odoo using Ctrl+C in its server terminal; leave PostgreSQL running.
3. Run in PowerShell:

```powershell
cd "C:\Users\Hamza\Desktop\Z\HopLand\Hopland_Receipt_Handoff_20.0.1.2.0"
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY_RECEIPT_HANDOFF.ps1
```

The installer backs up the installed addon and database, updates the addon, upgrades its database objects, and runs verification. The default database is `hopland_demo_v2`. It uses the existing Python environment and `community\hopland.conf`. Optional parameters: `-ProjectRoot` and `-Database`.

Backups: `birthday_addon_backups\before_receipt_handoff_<timestamp>`. PostgreSQL credentials are read from the configuration and not printed. The database dump does not include the separate filestore; the update does not delete filestore contents. If backup fails, copying the addon does not start. If upgrade or verification fails, keep Odoo stopped and share the error/log instead of repeatedly retrying.

Wait for **HOPLAND_RECEIPT_HANDOFF_OK**. The output should include the existing receipt reference and the number of accountants notified. If it says no eligible accountant, ensure an active internal Bookkeeper has this branch in allowed companies. The review is still visible in the branch's list; rerunning the private backfill as administrator can assign it after permissions are corrected.

4. Restart Odoo:

```powershell
cd "C:\Users\Hamza\Desktop\Z\HopLand\community"
& ".\.venv_hopland\Scripts\python.exe" ".\odoo-bin" "-c" ".\hopland.conf"
```

5. Log the Accountant out and back in, select **Hopland – Al Yasmin**, then open **Accounting → Purchase receipts** or the activity clock.
6. Open the YAS/IN/00001 review and check supplier, booking, receipt and PO references, quantity 1, and PO total 172.50 SAR. Leave it To review while supplier billing is pending.

This installer does not cancel P00001. Confirm separately that the superseded service purchase order is cancelled, as discussed during the demo.

## Validation and limits

Passed locally: 14 handoff tests and 12 existing workflow tests using lightweight ORM substitutes; 8 existing POS notification assertions; Python syntax; XML against the official Odoo 20 import schema; view inheritance selectors; access-file operation and ID checks. Handoff tests cover post-completion hook ordering, snapshots, HTML escaping, retries, partial deliveries, returns, ignored movements, company mismatch, recipient availability, authorization, bill-action filtering and menu preservation.

Odoo 20 upstream source was checked for the stock completion hook, `stock.move.uom_id`, activity-type model field, menu group field and XML conversion behavior.

This development environment has no running Odoo/PostgreSQL server. Full ORM/browser and Windows installation checks therefore remain to run on the demo system. The supplied verification runs against that real database after upgrade: it checks menus, sources, repeat processing, accountant record access, company isolation, form rendering metadata and existing bill search. It rolls back its own transaction. Upgrade-generated review records/activities remain committed by the preceding upgrade.

Acceptance after installation:
- Existing receipt appears once, with an Accounting activity.
- Open/reprocess does not duplicate the review/task.
- A newly validated party purchase receipt automatically appears with a task.
- A user without access to the receipt's branch cannot see its review.
- Mark reviewed records the accountant and closes generated review activities, without posting a bill.

## Recovery

Keep the printed backup and logs. Restore the backed-up addon and database together if rollback is required; copying old Python files alone does not reverse database changes. Retain the existing filestore. No automatic database replacement is performed.
