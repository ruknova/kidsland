"""Run on a disposable Odoo 20 database, never against the business database."""
import base64
from uuid import uuid4

from odoo import Command, fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError, AccessError


@tagged('post_install', '-at_install', 'hopland_petty_cash')
class TestPettyCash(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Account = cls.env['account.account']
        def account(code, name, kind, reconcile=False):
            return cls.Account.create({'code': code, 'name': name, 'account_type': kind,
                'reconcile': reconcile, 'company_ids': [Command.set(cls.company.ids)]})
        cls.cash = account('PC1001', 'Test petty cash', 'asset_cash')
        cls.expense = account('PC4001', 'Test petty cash expense', 'expense')
        cls.payable = account('PC2001', 'Test petty cash payable', 'liability_payable', True)
        cls.offset = account('PC1002', 'Test funding offset', 'asset_current', True)
        cls.cash_journal = cls.env['account.journal'].create({'name': 'Test petty cash', 'code': 'PCT',
            'type': 'cash', 'company_id': cls.company.id, 'default_account_id': cls.cash.id})
        cls.bill_journal = cls.env['account.journal'].create({'name': 'Test petty cash bills', 'code': 'PCB',
            'type': 'purchase', 'company_id': cls.company.id, 'default_account_id': cls.expense.id})
        cls.misc = cls.env['account.journal'].create({'name': 'Test funding', 'code': 'PCF',
            'type': 'general', 'company_id': cls.company.id})
        cls.cash_journal.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual').payment_account_id = cls.cash
        def user(name, groups):
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': name, 'login': name + str(uuid4()), 'company_id': cls.company.id,
                'company_ids': [Command.set(cls.company.ids)],
                'group_ids': [Command.set([cls.env.ref('base.group_user').id] + [cls.env.ref(g).id for g in groups])],
            })
        cls.buyer = user('PC Buyer', ['purchase.group_purchase_user'])
        cls.other = user('PC Other buyer', ['purchase.group_purchase_user'])
        cls.accountant = user('PC Accountant', ['account.group_account_user'])
        cls.vendor = cls.env['res.partner'].with_company(cls.company).create({
            'name': 'PC Test Vendor', 'supplier_rank': 1, 'property_account_payable_id': cls.payable.id})
        cls.fund = cls.env['hopland.petty.cash.fund'].create({
            'name': 'Test purchasing fund', 'company_id': cls.company.id, 'department': 'Purchasing',
            'custodian_id': cls.buyer.id, 'user_ids': [Command.set(cls.buyer.ids)],
            'reviewer_id': cls.accountant.id, 'journal_id': cls.cash_journal.id,
            'bill_journal_id': cls.bill_journal.id, 'expense_account_id': cls.expense.id, 'approved_float': 2000,
        })
        cls.Payment = cls.env['hopland.petty.cash.payment']
        funding = cls.env['account.move'].create({'journal_id': cls.misc.id, 'date': fields.Date.today(),
            'line_ids': [Command.create({'name': 'Funding', 'account_id': cls.cash.id, 'debit': 2000}),
                         Command.create({'name': 'Funding', 'account_id': cls.offset.id, 'credit': 2000})]})
        funding.action_post()

    def request(self, **extra):
        ref = 'TEST-' + str(uuid4())
        vals = {'fund_id': self.fund.id, 'partner_id': self.vendor.id, 'purpose': 'Cleaning supplies',
            'vendor_reference': ref, 'date': fields.Date.today(), 'invoice_date': fields.Date.today(),
            'source': 'expense', 'net_amount': 100, 'amount': 100,
            'receipt': base64.b64encode(b'%PDF-1.4\n' + ref.encode() + b'\n%%EOF'), 'receipt_filename': ref + '.pdf'}
        vals.update(extra)
        return self.Payment.with_user(self.buyer).create(vals)

    def test_confirm_posts_once_with_attachment_and_review(self):
        request = self.request()
        request.action_confirm()
        trusted = request.sudo()
        self.assertEqual(trusted.state, 'paid')
        self.assertEqual(trusted.bill_id.state, 'posted')
        self.assertEqual(trusted.bill_id.amount_residual, 0)
        self.assertEqual(trusted.payment_id.move_id.state, 'posted')
        self.assertEqual(self.fund._ledger_balance(), 1900)
        self.assertEqual(trusted.posted_by, self.buyer)
        self.assertTrue(self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'), ('res_id', '=', trusted.bill_id.id)]))
        original_payment = trusted.payment_id
        request.action_confirm()
        self.assertEqual(trusted.payment_id, original_payment)
        self.assertEqual(self.fund._ledger_balance(), 1900)
        request.with_user(self.accountant).action_review()
        self.assertEqual(trusted.state, 'reviewed')
        self.assertEqual(self.fund._ledger_balance(), 1900)

    def test_missing_receipt_blocks_all_posting(self):
        request = self.request(receipt=False)
        with self.assertRaises(UserError):
            request.action_confirm()
        self.assertFalse(request.sudo().payment_id)
        self.assertEqual(self.fund._ledger_balance(), 2000)

    def test_insufficient_balance_and_limit(self):
        request = self.request(net_amount=2001, amount=2001)
        with self.assertRaises(UserError):
            request.action_confirm()
        self.assertEqual(self.fund._ledger_balance(), 2000)
        self.fund.per_payment_limit = 50
        request = self.request()
        with self.assertRaises(UserError):
            request.action_confirm()

    def test_mismatched_total_rolls_back_bill(self):
        request = self.request(amount=99)
        with self.assertRaises(UserError):
            request.action_confirm()
        self.assertFalse(self.env['account.move'].search([('ref', '=', request.vendor_reference)]))
        self.assertFalse(request.sudo().payment_id)
        self.assertEqual(self.fund._ledger_balance(), 2000)

    def test_assignment_and_direct_field_forgery(self):
        request = self.request()
        with self.assertRaises(AccessError):
            request.with_user(self.other).action_confirm()
        with self.assertRaises(AccessError):
            request.write({'state': 'paid'})
        with self.assertRaises(AccessError):
            self.fund.with_user(self.buyer).write({'approved_float': 99999})
        self.assertFalse(self.Payment.with_user(self.other).search([('id', '=', request.id)]))
        with self.assertRaises(AccessError):
            request.with_user(self.buyer).write({'fund_id': self.fund.id, 'payment_id': 1})

    def test_duplicate_reference_and_file(self):
        request = self.request()
        request.action_confirm()
        duplicate = self.request(vendor_reference=request.vendor_reference)
        with self.assertRaises(UserError):
            duplicate.action_confirm()
        duplicate_file = self.request(receipt=request.receipt)
        with self.assertRaises(UserError):
            duplicate_file.action_confirm()
        self.assertEqual(self.fund._ledger_balance(), 1900)

    def test_posted_requests_cannot_be_altered_or_deleted(self):
        request = self.request()
        request.action_confirm()
        with self.assertRaises(AccessError):
            request.write({'amount': 1})
        with self.assertRaises(AccessError):
            request.write({'receipt': False})
        with self.assertRaises(UserError):
            request.unlink()
        with self.assertRaises(UserError):
            request.copy()

    def test_tax_and_actual_amount(self):
        tax = self.env['account.tax'].create({'name': 'PC VAT 15%', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': self.company.id, 'price_include_override': 'tax_excluded'})
        self.fund.allowed_tax_ids = [Command.set(tax.ids)]
        request = self.request(net_amount=150, amount=172.5, tax_ids=[Command.set(tax.ids)])
        request.action_confirm()
        self.assertEqual(request.sudo().bill_id.amount_total, 172.5)
        self.assertEqual(self.fund._ledger_balance(), 1827.5)

    def test_existing_bill_reuses_invoice(self):
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'journal_id': self.bill_journal.id,
            'partner_id': self.vendor.id, 'invoice_date': fields.Date.today(), 'ref': 'PC-EXISTING',
            'invoice_line_ids': [Command.create({'name': 'Existing', 'quantity': 1, 'price_unit': 100,
                'account_id': self.expense.id, 'tax_ids': [Command.clear()]})]})
        bill.action_post()
        request = self.request(source='bill', bill_number=bill.name, vendor_reference=bill.ref, net_amount=0)
        request.action_confirm()
        self.assertEqual(request.sudo().bill_id, bill)
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(self.env['account.move'].search_count([('ref', '=', 'PC-EXISTING'), ('move_type', '=', 'in_invoice')]), 1)

    def test_existing_vendor_reference_does_not_create_duplicate(self):
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'journal_id': self.bill_journal.id,
            'partner_id': self.vendor.id, 'ref': 'PC-DUPLICATE'})
        request = self.request(vendor_reference='pc-duplicate')
        with self.assertRaises(UserError):
            request.action_confirm()
        self.assertTrue(bill.exists())
        self.assertEqual(self.fund._ledger_balance(), 2000)

    def test_date_and_context_bypass_rejected(self):
        request = self.request(date=fields.Date.add(fields.Date.today(), days=1))
        with self.assertRaises(UserError):
            request.with_context(check_move_validity=False, force_payment_move=True).action_confirm()
        request = self.request()
        request.with_context(check_move_validity=False, force_payment_move=True).action_confirm()
        self.assertEqual(request.sudo().payment_id.outstanding_account_id, self.cash)

    def test_cross_company_fund_inaccessible(self):
        company = self.env['res.company'].create({'name': 'PC Inaccessible company'})
        self.buyer.write({'company_ids': [Command.set(company.ids)], 'company_id': company.id})
        with self.assertRaises(AccessError):
            self.request()

    def test_context_cannot_forge_confirmation(self):
        request = self.request()
        forged = self.Payment.with_user(self.buyer).with_context(
            default_state='paid', default_posted_by=self.accountant.id,
            default_payment_id=1, default_reviewed_by=self.accountant.id,
        ).create({'fund_id': self.fund.id, 'partner_id': self.vendor.id,
                  'vendor_reference': 'PC-CONTEXT', 'purpose': 'Test', 'amount': 100})
        self.assertEqual(forged.state, 'draft')
        self.assertFalse(forged.sudo().payment_id)
        self.assertFalse(forged.posted_by)
        self.assertFalse(forged.reviewed_by)

    def test_purchase_order_bill_keeps_purchase_links(self):
        product = self.env['product.product'].create({'name': 'PC Test service', 'type': 'service',
            'purchase_method': 'purchase', 'property_account_expense_id': self.expense.id,
            'supplier_taxes_id': [Command.clear()]})
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id, 'company_id': self.company.id,
            'order_line': [Command.create({'product_id': product.id, 'name': 'Service', 'product_qty': 1,
                'price_unit': 100, 'tax_ids': [Command.clear()], 'date_planned': fields.Datetime.now()})]})
        po.button_confirm()
        request = self.request(source='purchase', purchase_id=po.id, net_amount=0)
        request.action_confirm()
        bill = request.sudo().bill_id
        self.assertEqual(bill.invoice_line_ids.purchase_line_id.order_id, po)
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(self.fund._ledger_balance(), 1900)

    def test_two_payments_cannot_exhaust_same_fund(self):
        first = self.request(net_amount=1500, amount=1500)
        second = self.request(net_amount=600, amount=600)
        first.action_confirm()
        with self.assertRaises(UserError):
            second.action_confirm()
        self.assertEqual(self.fund._ledger_balance(), 500)
        self.assertEqual(self.fund.balance_epoch, 1)

    def test_confirmation_does_not_create_statement_line(self):
        count = self.env['account.bank.statement.line'].search_count([('journal_id', '=', self.cash_journal.id)])
        self.request().action_confirm()
        self.assertEqual(self.env['account.bank.statement.line'].search_count([
            ('journal_id', '=', self.cash_journal.id)]), count)
