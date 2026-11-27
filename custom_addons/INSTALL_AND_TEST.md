# Hopland Purchasing Petty Cash — 20.0.1.0.0

This adds a separate `hopland_petty_cash` addon. It does not replace `hopland_birthday_pos`, reset data, change users' roles, create funds, or add money. Keep the existing 2,000 SAR journal funding.

## Verification status

Built against the uploaded current `custom_addons.zip` and checked against Odoo Community 20.0 source. The addon imports under Odoo 20.0, Python syntax and XML schema checks pass, and 14 standalone validation tests pass. Database-backed installation, accounting posting, UI and integration tests have **not** run here: the isolated environment cannot start a PostgreSQL server. The included 16 integration tests must be run in a disposable database/copy before relying on the workflow. See `TEST_REPORT.md`.

This is an implementation candidate for the demo, not a production certification. Your exact Enterprise build and local customizations still need the acceptance test below.

## Install without overwriting existing modules

1. Take a fresh backup of `hopland_demo_v2`, including the filestore, and restore a separate test copy with a different name. The backup used earlier in training predates later transactions. Ensure the test database is allowed by your Odoo `dbfilter`. Keep scheduled actions and outbound integrations disabled in the copy.
2. Extract this ZIP into a temporary folder. Copy **only the `hopland_petty_cash` folder** into:

   `C:\Users\Hamza\Desktop\Z\HopLand\custom_addons\`

   The result must contain `custom_addons\hopland_petty_cash\__manifest__.py`. Do not replace the existing birthday addon or its configuration.
3. Restart Odoo using its working `.venv_hopland` environment. As Administrator, activate developer mode, open Apps, **Update Apps List**, remove the Apps filter, search **Hopland Purchasing Petty Cash**, and install it in the test copy.
4. After tests pass on the copy, install this same addon in the demo database. No upgrade of the birthday addon is required.

Optional command for a test database (replace `YOUR_TEST_DATABASE`; stop the existing Odoo process before running):

```powershell
cd "C:\Users\Hamza\Desktop\Z\HopLand\community"
& ".\.venv_hopland\Scripts\python.exe" ".\odoo-bin" -c ".\hopland.conf" -d "YOUR_TEST_DATABASE" -i hopland_petty_cash --test-enable --test-tags /hopland_petty_cash --stop-after-init --no-http
```

Do not run the integration tests against the live/demo business database. The test fixtures create their own users, funds and accounting documents in test transactions.

## One-time fund setup

Use Accounting access in **Hopland – Al Yasmin**. Open **Accounting → Petty Cash → Department funds → New**.

| Field | Select / enter |
|---|---|
| Name | Al Yasmin — Purchasing Petty Cash |
| Company | Hopland – Al Yasmin |
| Department | Purchasing |
| Custodian | Hopland Purchasing |
| Authorized purchasing users | Hopland Purchasing (plus any explicitly authorized colleagues) |
| Accounting reviewer | Hopland Accountant |
| Approved float | 2,000.00 SAR |
| Per-payment limit | Optional delegated approval ceiling; 0 means no extra per-payment ceiling |
| Cash journal | Existing Al Yasmin — Purchasing Petty Cash, CSH2 |
| Cash account | Existing 105002, populated from that journal |
| Bill journal | Existing Purchases journal belonging to this company |
| Expense account | Accounting-approved consumables/operating expense account for purchases with no PO |
| Allowed taxes | The appropriate purchase VAT tax(es), e.g. 15% purchase VAT with tax-exclusive pricing for the sample |

The custodian and authorized users must have Purchasing access and access to this company. The reviewer must have Accounting access and access to this company. Do not grant Purchasing broad Accounting rights just to use this addon.

For the existing cash journal, the **Manual outgoing payment method's payment account must equal its cash account (105002)**. The code checks this and stops if it differs. The incoming method was also configured to this account during your setup. Creating the fund does not create a cash opening balance. Its available balance should already be **2,000 SAR** from the posted funding.

The approved float is a reference amount, not a monthly budget or an automatic funding ceiling. Monthly replenishment, early replenishment, and extra funding remain Accounting decisions and are recorded with supported internal transfers. Set a per-payment limit to enforce a delegated spending ceiling. A separate request/approval/funding automation is not included in this release.

## Purchasing's everyday flow

Open **Purchase → Petty Cash → Payments → New**. The first accessible fund defaults automatically; verify it before paying.

1. Select vendor, document reference, purpose, payment/document dates and source.
2. Enter the amount actually paid, including tax; upload the vendor receipt as PDF/PNG/JPEG (10 MB maximum).
3. Click **Confirm petty-cash payment** and confirm that payment was made from that cash fund.

This records a payment already handed to the vendor. It does not transfer money through a bank, payment gateway or cash device.

The action creates or selects the correct vendor bill, posts it if draft, creates one native outbound cash payment, reconciles the bill's payable lines, stores a receipt copy on the bill, and assigns the configured accountant a review activity. The department's available ledger balance decreases immediately. Accounting must not enter another bill/payment for that same receipt.

### Sources

- **Direct expense (no PO):** suitable for small consumables/services with no inventory movement. Enter the pre-tax amount and select the allowed tax. The tax-inclusive total must match the amount paid exactly within currency precision. Taxes that include tax in the entered price are rejected in this first version; Accounting should configure an appropriate tax-exclusive purchase tax, not change an existing tax used by other documents. No OCR or automatic tax extraction is performed.
- **Purchase order:** select the company's confirmed PO and matching vendor. An existing sole draft/posted bill is reused. If none exists, the addon creates a bill from positive native `qty_to_invoice` lines, preserving purchase-line links and native taxes. Products billed on received quantities need a receipt first. It does not mark goods received. If there are multiple bills, use Existing vendor bill. Check that the PO price is correct first; the addon deliberately stops on a receipt/PO/bill total mismatch.
- **Existing vendor bill:** enter the exact posted Odoo bill number and vendor receipt reference. Only that vendor, company and currency are accepted. The full outstanding balance is paid; another invoice is not created.

This version handles company-currency, same-day purchasing payments and full outstanding bill settlements. Partial payments, supplier advances before a bill, foreign currency, backdating, and refunds go through Accounting's native workflows. Do not create a duplicate expense to bypass these checks.

## First demo purchase: expected balance 1,885 SAR

Use the included **DEMO_PC_001_Receipt.pdf**, clearly marked as a simulated receipt, in the test database only. It is not a real supplier tax invoice.

| Field | Value |
|---|---|
| Fund | Existing Al Yasmin Purchasing fund |
| Vendor | Demo Cake Supplier |
| Vendor invoice / receipt number | DEMO-PC-001 |
| Purpose | Disposable party supplies — petty cash demo |
| Source | Direct expense (no PO) |
| Payment date | Today (Purchasing payments cannot be backdated) |
| Vendor document date | 25 November 2026, or the test receipt date |
| Expense amount before tax | 100.00 SAR |
| Purchase tax | Appropriate 15% purchase VAT, tax excluded |
| Amount paid including tax | 115.00 SAR |
| Receipt | DEMO_PC_001_Receipt.pdf |

Expected: one posted bill, one posted cash payment, bill residual zero, fund balance **2,000 − 115 = 1,885 SAR**, one Accounting review activity, receipt attached to the vendor bill. Do not reuse the already-paid cake bill P00007/BILL0005 for this new expense.

Accounting opens **Accounting → Petty Cash → Review payments**, checks the receipt and linked bill/payment, adds review notes, then **Mark reviewed**. Review does not create another payment.

The custom fund balance and the cash general ledger are authoritative for this workflow. Do not create an extra cash-statement withdrawal for the same payment: the native cash payment has already reduced cash. A bank/cash matching screen's statement running balance may not include these direct cash payments.

## Acceptance tests before use

- A purchasing user assigned to the fund can confirm the sample and gets the expected bill/payment/balance.
- A different purchasing user cannot list, read or confirm this fund's requests. Company isolation must hold even when IDs are supplied directly.
- Missing/wrong-type/oversized receipt, blank reference, zero/negative amount, tax mismatch, wrong company or vendor, insufficient cash, or exceeded per-payment limit blocks confirmation without leaving a bill/payment behind.
- Confirming the same request twice creates only one payment.
- A new request with the same vendor document number (ignoring case/outer spaces), or the same receipt file under another filename, is rejected.
- Two different authorized users concurrently trying to spend 1,500 + 600 from a 2,000 fund: at most the first succeeds; the other must retry/check the remaining balance. Test with separate browser sessions. The code locks and mutates a shared fund row to support PostgreSQL serialization retries; this concurrency case is not executed here.
- PO-paid invoices retain their purchase-line links; a billable quantity of zero blocks new PO billing.
- An existing bill is reused, never duplicated; an already-paid bill cannot be paid again.
- Purchasing cannot edit/delete a confirmed request, replace its receipt, set posting IDs/state through RPC or context defaults, or alter the fund configuration.
- Accounting review leaves the cash balance unchanged.
- Replenishing 115 through Accounting's normal bank-to-cash internal transfer brings the fund back to 2,000; approved extra funding may increase it further.

The balance serialization protects payments through this addon. Accounting retains its normal authority to post/correct other ledger transactions. Coordinate manual cash-account corrections with Purchasing; this addon does not override every native posting route or bank integration.

## Corrections and audit

Confirmed requests are immutable; Accounting uses native bill credit notes, payment reversal/unreconciliation or other supported corrections after checking the linked entries. Keep a review note documenting the correction. The request retains the original confirmation history; use the native documents and ledger to verify subsequent reversals. Do not delete or reset previously paid birthday transactions.

No existing department users are automatically assigned. Do not assign a user to a fund unless Accounting authorizes that spending. Users with additional existing Accounting rights retain those rights; the addon does not remove them.

## Rollback

Before any use, an administrator can remove the unneeded addon in the test copy or restore the pre-install copy. After financial transactions exist, do not uninstall to undo payments: preserve the audit trail and use native corrections, or restore the full pre-install database/filestore backup only when intentionally discarding all subsequent demo activity.
