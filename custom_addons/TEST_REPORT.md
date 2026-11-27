# Verification report — Hopland Purchasing Petty Cash 20.0.1.0.0

## Executed successfully

- 14 standalone validation tests: missing receipt/name, PDF/PNG/JPEG signatures, invalid encoding, mismatched extension, disguised HTML, receipt size limit, reference normalization and company/vendor scope, blank reference, non-finite/non-positive amounts, and duplicate-file identity regardless of filename.
- Python AST parsing for all addon Python files.
- Addon import under Python 3.12 and Odoo Community **20.0**.
- Integration test suite import under that runtime (test bodies not executed).
- XML validation against Odoo's `import_xml.rng` schema.
- Manifest references resolve to included files.
- View field names resolve to declared model fields or known inherited mail fields.
- Access-rule expressions use the current Odoo 20 `ir.access` evaluation names (`user`, `company_ids`), matching the uploaded project's ACL format.
- All **27 extracted current source files** from the uploaded addon remain byte-for-byte unchanged. The deliverable contains only the new addon and its documentation/sample receipt.

Public reference runtime: https://github.com/odoo/odoo/tree/20.0
Commit used for compatibility inspection/import: `4e433a14544daa9129624b5dd8b24e7f0603843a`.
The user's Windows Enterprise runtime was not available here; its exact revision is not known.

## Not executed — requires the user's disposable Odoo test database

The 16 integration tests in `hopland_petty_cash/tests/test_petty_cash.py` cover posting, bill reconciliation, tax totals, PO line links, existing bill reuse, receipt requirement, balance/limit controls, protected fields, company/assignment restrictions, duplicate references/files, rollback after a failed total check, repeat confirmation, context-forgery protection, and no duplicate cash-statement line.

No claims are made that these database tests pass. A local PostgreSQL runtime was prepared, but the environment denied creation of the socket needed to start the database server. No connection to or changes in the user's database occurred.

Full module installation, view loading in a browser, the Enterprise localization, and the actual accounting post/reconciliation path must be checked in the target test copy before use. Separate-session concurrent spending is an explicit manual acceptance case, not an executed automated test here.

## Design checks

- One fund per cash journal and per company/cash account.
- Available cash is read from posted ledger entries dated through the payment date.
- Confirmation uses a database savepoint and a locked, mutated fund row, so a concurrent request must refresh its PostgreSQL snapshot through transaction retry. A row lock without an update would not suffice under repeatable-read isolation.
- No user-supplied accounting bypass context is passed to elevated native posting operations.
- Elevated operations are limited to a server-validated assigned fund, company, vendor, configured journals/account/taxes and a receipt-backed amount. Native accounting methods create/post/reconcile documents.
- Native PO quantity-to-invoice policy is preserved; confirmation does not receive stock.
- Protected state/link/audit fields cannot be supplied or edited by Purchasing, including through `default_*` context values.
- Confirmed request receipts remain immutable. The bill gets its own attached copy.
- Duplicate confirmation is idempotent. Vendor-reference and receipt hashes also have database uniqueness constraints.
- Accounting review adds a review stamp/activity feedback only; it creates no financial transaction.
- No module installation hooks create money, configure users, or modify existing business transactions.

## Boundaries

This release focuses on purchasing confirmation and accounting visibility. A funding approval/request wizard, bank synchronization, monthly automatic replenishment, OCR, partial/advance supplier payments, foreign currencies, and native-document reversal automation are not implemented. Accounting's normal transfer and correction workflows remain available.

Standalone checks can be repeated with:

```powershell
& ".\.venv_hopland\Scripts\python.exe" "..\custom_addons\hopland_petty_cash\tests\test_validation_standalone.py"
```

See `INSTALL_AND_TEST.md` for the database test command and the first 115 SAR receipt scenario.
