import math

from markupsafe import Markup

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .validation import MAX_RECEIPT_BYTES, receipt_file, reference_key, positive_amount


class PettyCashFund(models.Model):
    _name = 'hopland.petty.cash.fund'
    _description = 'Department petty cash fund'
    _inherit = ['mail.thread']
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    department = fields.Char(required=True, tracking=True)
    custodian_id = fields.Many2one('res.users', required=True, tracking=True)
    user_ids = fields.Many2many('res.users', string='Authorized purchasing users', tracking=True)
    reviewer_id = fields.Many2one('res.users', required=True, string='Accounting reviewer')
    journal_id = fields.Many2one('account.journal', required=True, check_company=True,
                                domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]")
    cash_account_id = fields.Many2one(related='journal_id.default_account_id', store=True)
    bill_journal_id = fields.Many2one('account.journal', required=True, check_company=True,
                                     domain="[('type', '=', 'purchase'), ('company_id', 'parent_of', company_id)]")
    expense_account_id = fields.Many2one('account.account', required=True, check_company=True,
                                        domain="[('account_type', 'in', ['expense', 'expense_direct_cost'])]")
    allowed_tax_ids = fields.Many2many('account.tax', check_company=True,
                                      string='Allowed taxes for direct expenses',
                                      domain="[('type_tax_use', '=', 'purchase')]")
    approved_float = fields.Monetary(required=True, tracking=True,
                                    help='Approved normal float. This does not create money or a ledger entry.')
    per_payment_limit = fields.Monetary(help='Optional delegated spending limit per payment. Zero means no extra limit.')
    available_balance = fields.Monetary(compute='_compute_balance', compute_sudo=False)
    balance_epoch = fields.Integer(default=0, readonly=True, copy=False)
    _journal_unique = models.Constraint('unique(journal_id)', 'This cash journal already has a petty cash fund.')
    _cash_unique = models.Constraint('unique(company_id, cash_account_id)', 'Use a dedicated cash account for each fund.')

    def _finance_only(self):
        if not self.env.su and not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Only Accounting may configure department funds.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._finance_only()
        return super().create(vals_list)

    def write(self, vals):
        self._finance_only()
        if {'company_id', 'journal_id'} & vals.keys():
            if self.env['hopland.petty.cash.payment'].sudo().search_count([
                    ('fund_id', 'in', self.ids), ('state', '!=', 'draft')]):
                raise UserError(_('A fund with confirmed payments cannot change company or cash journal.'))
        return super().write(vals)

    def unlink(self):
        self._finance_only()
        return super().unlink()

    @api.constrains('company_id', 'journal_id', 'bill_journal_id', 'expense_account_id',
                    'allowed_tax_ids', 'approved_float', 'per_payment_limit', 'custodian_id', 'user_ids', 'reviewer_id')
    def _check_config(self):
        for fund in self:
            if fund.journal_id.type != 'cash' or fund.journal_id.company_id != fund.company_id:
                raise ValidationError(_('Choose this company’s dedicated cash journal.'))
            if fund.bill_journal_id.type != 'purchase' or not fund.bill_journal_id.filtered_domain(
                    fund.bill_journal_id._check_company_domain(fund.company_id)
            ):
                raise ValidationError(_('Choose a purchase journal available to this branch.'))
            if fund.journal_id.currency_id and fund.journal_id.currency_id != fund.currency_id:
                raise ValidationError(_('This version supports company-currency cash funds only.'))
            if fund.cash_account_id.account_type != 'asset_cash':
                raise ValidationError(_('The fund journal needs a Bank and Cash type account.'))
            if fund.expense_account_id.account_type not in ('expense', 'expense_direct_cost'):
                raise ValidationError(_('Choose an expense account for direct purchases.'))
            if not positive_amount(fund.approved_float) or not math.isfinite(fund.per_payment_limit) or fund.per_payment_limit < 0:
                raise ValidationError(_('The approved float must be positive and the payment limit cannot be negative.'))
            for user in fund.user_ids | fund.custodian_id | fund.reviewer_id:
                if not user.active or user.share or fund.company_id not in user.company_ids:
                    raise ValidationError(_('Every responsible user must be an active internal user of this company.'))
            if not fund.reviewer_id.has_group('account.group_account_user'):
                raise ValidationError(_('The reviewer must have Accounting access.'))
            for user in fund.user_ids | fund.custodian_id:
                if not user.has_group('purchase.group_purchase_user'):
                    raise ValidationError(_('Fund users and the custodian need Purchasing access.'))
            if fund.allowed_tax_ids.filtered(lambda t: t.type_tax_use != 'purchase'):
                raise ValidationError(_('Only purchase taxes can be allowed.'))

    def _check_spender(self):
        self.ensure_one()
        self.check_access('read')
        if self.company_id not in self.env.companies or not self.active:
            raise AccessError(_('The fund is inactive or outside your selected companies.'))
        if not (self.env.user.has_group('purchase.group_purchase_user') and
                self.env.user in (self.user_ids | self.custodian_id)):
            raise AccessError(_('Only Purchasing users assigned to this fund may confirm its payments.'))

    def _ledger_balance(self, through_date=None):
        self.ensure_one()
        # Read only this fund's account after caller access is verified. No cached wallet balance.
        domain = [('company_id', '=', self.company_id.id), ('account_id', '=', self.cash_account_id.id),
                  ('parent_state', '=', 'posted')]
        if through_date:
            domain.append(('date', '<=', through_date))
        result = self.env['account.move.line'].sudo()._read_group(domain, aggregates=['balance:sum'])
        return result[0][0] if result else 0.0

    def _compute_balance(self):
        for fund in self:
            fund.check_access('read')
            fund.available_balance = fund._ledger_balance(fields.Date.context_today(fund)) if fund.id else 0.0

    def _payment_method(self):
        self.ensure_one()
        self._check_config()
        methods = self.journal_id.outbound_payment_method_line_ids.filtered(
            lambda m: m.code == 'manual' and m.payment_account_id == self.cash_account_id)
        if len(methods) != 1:
            raise UserError(_('Accounting must configure one Manual outgoing method using the fund’s cash account.'))
        return methods


class PettyCashPayment(models.Model):
    _name = 'hopland.petty.cash.payment'
    _description = 'Purchasing petty cash payment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(default='New', readonly=True, copy=False)
    fund_id = fields.Many2one('hopland.petty.cash.fund', required=True, ondelete='restrict', tracking=True,
                              default=lambda self: self.env['hopland.petty.cash.fund'].search([], limit=1))
    company_id = fields.Many2one(related='fund_id.company_id', store=True)
    currency_id = fields.Many2one(related='fund_id.currency_id')
    available_balance = fields.Monetary(related='fund_id.available_balance')
    requested_by = fields.Many2one('res.users', readonly=True, default=lambda self: self.env.user)
    partner_id = fields.Many2one('res.partner', required=True, check_company=True, string='Vendor')
    vendor_reference = fields.Char(required=True, string='Vendor invoice / receipt number', tracking=True)
    purpose = fields.Char(required=True, tracking=True)
    date = fields.Date(default=fields.Date.context_today, required=True, string='Payment date')
    invoice_date = fields.Date(default=fields.Date.context_today, required=True, string='Vendor document date')
    source = fields.Selection([('expense', 'Direct expense (no PO)'), ('purchase', 'Purchase order'),
                               ('bill', 'Existing vendor bill')], default='expense', required=True)
    purchase_id = fields.Many2one('purchase.order', check_company=True, ondelete='restrict',
                                  domain="[('company_id', '=', company_id), ('state', '=', 'purchase')]")
    bill_number = fields.Char(string='Existing bill number', help='Exact Odoo number, for example BILL/2026/11/0005.')
    net_amount = fields.Monetary(string='Expense amount before tax')
    allowed_tax_ids = fields.Many2many(related='fund_id.allowed_tax_ids')
    tax_ids = fields.Many2many('account.tax', check_company=True, string='Purchase taxes',
                              domain="[('id', 'in', allowed_tax_ids)]")
    amount = fields.Monetary(required=True, string='Amount paid (including tax)', tracking=True)
    receipt = fields.Binary(attachment=False, copy=False, string='Vendor receipt (PDF / image)')
    receipt_filename = fields.Char(copy=False)
    state = fields.Selection([('draft', 'Draft'), ('paid', 'Paid — to review'), ('reviewed', 'Reviewed')],
                              default='draft', required=True, readonly=True, tracking=True, copy=False)
    bill_id = fields.Many2one('account.move', readonly=True, copy=False, check_company=True, ondelete='restrict')
    payment_id = fields.Many2one('account.payment', readonly=True, copy=False, check_company=True, ondelete='restrict')
    bill_display = fields.Char(readonly=True, copy=False)
    payment_display = fields.Char(readonly=True, copy=False)
    posted_by = fields.Many2one('res.users', readonly=True, copy=False)
    posted_at = fields.Datetime(readonly=True, copy=False)
    reviewed_by = fields.Many2one('res.users', readonly=True, copy=False)
    reviewed_at = fields.Datetime(readonly=True, copy=False)
    review_notes = fields.Text()
    duplicate_key = fields.Char(readonly=True, copy=False, index=True)
    receipt_hash = fields.Char(readonly=True, copy=False, index=True)
    _duplicate_reference = models.Constraint('unique(duplicate_key)', 'This vendor document already has a petty cash payment.')
    _duplicate_receipt = models.Constraint('unique(company_id, receipt_hash)', 'This receipt file was already used for a confirmed payment.')
    _payment_unique = models.Constraint('unique(payment_id)', 'A payment cannot be linked to two petty cash requests.')

    @api.onchange('source')
    def _onchange_source(self):
        if self.source != 'expense':
            self.net_amount = 0
            self.tax_ids = [Command.clear()]
        if self.source != 'purchase':
            self.purchase_id = False
        if self.source != 'bill':
            self.bill_number = False

    @api.onchange('fund_id')
    def _onchange_fund(self):
        self.tax_ids = [Command.clear()]
        self.purchase_id = False
        self.bill_number = False

    _draft_fields = {'fund_id', 'partner_id', 'vendor_reference', 'purpose', 'date', 'invoice_date',
                     'source', 'purchase_id', 'bill_number', 'net_amount', 'tax_ids', 'amount',
                     'receipt', 'receipt_filename'}

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if set(vals) - self._draft_fields:
                    raise AccessError(_('Create a draft using the payment form; posting fields cannot be supplied.'))
                if not vals.get('fund_id'):
                    raise UserError(_('Choose your assigned petty cash fund.'))
                self.env['hopland.petty.cash.fund'].browse(vals['fund_id'])._check_spender()
        # Force security-sensitive defaults even when an RPC caller supplies default_* context keys.
        vals_list = [dict(vals, state='draft', name='New', requested_by=self.env.uid,
                          bill_id=False, payment_id=False, bill_display=False, payment_display=False,
                          posted_by=False, posted_at=False, reviewed_by=False, reviewed_at=False,
                          duplicate_key=False, receipt_hash=False, review_notes=False) for vals in vals_list]
        return super().create(vals_list)

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM hopland_petty_cash_payment WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def write(self, vals):
        if not self.env.su:
            self.check_access('write')
            for request in self.sorted('id'):
                request._lock()
                if set(vals) <= {'review_notes'} and self.env.user.has_group('account.group_account_user'):
                    continue
                if request.state != 'draft' or set(vals) - self._draft_fields:
                    raise AccessError(_('Confirmed payments are immutable. Accounting reviews or corrects the linked accounting documents.'))
                request.fund_id._check_spender()
                if vals.get('fund_id'):
                    self.env['hopland.petty.cash.fund'].browse(vals['fund_id'])._check_spender()
        return super().write(vals)

    def unlink(self):
        for request in self.sorted('id'):
            request._lock()
            if request.state != 'draft':
                raise UserError(_('Confirmed petty cash payments cannot be deleted.'))
        return super().unlink()

    def copy(self, default=None):
        raise UserError(_('Create a new request; receipt-backed payments cannot be duplicated.'))

    def _trusted(self):
        # Never propagate user-supplied accounting bypass flags into privileged native operations.
        return self.sudo().with_context({}, allowed_company_ids=[self.company_id.id]).with_company(self.company_id)

    def _check_document(self):
        self.ensure_one()
        if not positive_amount(self.amount) or self.currency_id.is_zero(self.amount):
            raise UserError(_('Enter a positive payment amount.'))
        if not self.purpose or not self.purpose.strip():
            raise UserError(_('Enter the business purpose.'))
        if self.date != fields.Date.context_today(self):
            raise UserError(_('Purchasing payments must be dated today. Ask Accounting to handle backdated or future transactions.'))
        if self.invoice_date > self.date:
            raise UserError(_('The vendor document date cannot be after the payment date.'))
        if self.partner_id.company_id and self.partner_id.company_id != self.company_id:
            raise UserError(_('Choose a vendor available to this company.'))
        if self.source != 'expense' and (self.net_amount or self.tax_ids):
            raise UserError(_('Clear direct-expense amounts/taxes when paying a PO or existing bill.'))
        if self.source != 'purchase' and self.purchase_id:
            raise UserError(_('Use the Purchase order source for a PO-linked payment.'))
        if self.source != 'bill' and self.bill_number:
            raise UserError(_('Use the Existing vendor bill source for a bill number.'))
        try:
            receipt = self.receipt
            if receipt and receipt.size > MAX_RECEIPT_BYTES:
                raise ValueError('The receipt must be 10 MB or smaller.')
            data, mime, digest = receipt_file(receipt.to_base64() if receipt else '', self.receipt_filename)
            key = reference_key(self.company_id.id, self.partner_id.commercial_partner_id.id, self.vendor_reference)
        except ValueError as error:
            raise UserError(str(error)) from error
        return data, mime, digest, key

    def _bill_for_payment(self):
        """Private, elevated only after fund/user/company/receipt/amount checks and locks."""
        self.ensure_one()
        Move = self.env['account.move']
        if self.source == 'bill':
            if not self.bill_number or not self.bill_number.strip():
                raise UserError(_('Enter the exact existing bill number.'))
            bill = Move.search([('name', '=', self.bill_number.strip()), ('company_id', '=', self.company_id.id),
                                ('commercial_partner_id', '=', self.partner_id.commercial_partner_id.id),
                                ('move_type', '=', 'in_invoice'), ('state', '=', 'posted')], limit=2)
            if len(bill) != 1:
                raise UserError(_('No unique posted vendor bill matches that number, vendor and company.'))
            return bill
        if self.source == 'purchase':
            po = self.purchase_id
            if not po or po.company_id != self.company_id or po.state != 'purchase':
                raise UserError(_('Select a confirmed purchase order in this company.'))
            if po.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError(_('The PO vendor must match the payment vendor.'))
            if po.currency_id != self.currency_id:
                raise UserError(_('Foreign-currency purchases require Accounting.'))
            self.env.cr.execute('SELECT id FROM purchase_order WHERE id = %s FOR UPDATE', [po.id])
            po.invalidate_recordset()
            bills = po.invoice_ids.filtered(lambda b: b.move_type == 'in_invoice' and b.state != 'cancel')
            if bills:
                if len(bills) != 1:
                    raise UserError(_('This PO has multiple bills. Use Existing vendor bill and its exact number.'))
                return bills
            # Native PO invoice preparation preserves purchase-line links, taxes and received-quantity policy.
            if 'qty_to_invoice' not in self.env['purchase.order.line']._fields:
                raise UserError(_('This Odoo build needs Accounting to create the PO bill first; then use Existing vendor bill.'))
            lines = po.order_line.filtered(lambda line: not line.display_type and line.qty_to_invoice > 0)
            if not lines:
                raise UserError(_('There are no quantities available to bill. Receive goods first when the product uses received quantities.'))
            vals = po._prepare_invoice()
            vals.update({'journal_id': self.fund_id.bill_journal_id.id, 'invoice_date': self.invoice_date,
                         'date': self.date, 'ref': self.vendor_reference.strip(),
                         'invoice_line_ids': [Command.create(dict(line._prepare_account_move_line(),
                                                                quantity=line.qty_to_invoice)) for line in lines]})
            return Move.create(vals)
        if not positive_amount(self.net_amount) or self.currency_id.is_zero(self.net_amount):
            raise UserError(_('Enter the direct expense amount before tax.'))
        if self.tax_ids - self.fund_id.allowed_tax_ids:
            raise UserError(_('Only Accounting-approved taxes may be used.'))
        if self.tax_ids.filtered(lambda tax: tax.price_include):
            raise UserError(_('Use tax-exclusive purchase taxes for direct expenses.'))
        # Search native bills too, not only this addon's payments; never silently duplicate an existing invoice.
        self.env['account.move'].flush_model(['ref', 'company_id', 'commercial_partner_id', 'move_type', 'state'])
        self.env.cr.execute('''SELECT id FROM account_move WHERE company_id = %s
            AND commercial_partner_id = %s AND move_type = 'in_invoice' AND state != 'cancel'
            AND lower(trim(ref)) = %s LIMIT 1''',
            [self.company_id.id, self.partner_id.commercial_partner_id.id, self.vendor_reference.strip().lower()])
        if self.env.cr.fetchone():
            raise UserError(_('This vendor reference already exists. Select its PO or Existing vendor bill instead.'))
        return Move.create({'move_type': 'in_invoice', 'company_id': self.company_id.id,
                            'journal_id': self.fund_id.bill_journal_id.id, 'partner_id': self.partner_id.id,
                            'currency_id': self.currency_id.id, 'invoice_date': self.invoice_date, 'date': self.date,
                            'ref': self.vendor_reference.strip(),
                            'invoice_line_ids': [Command.create({'name': self.purpose,
                                'account_id': self.fund_id.expense_account_id.id, 'quantity': 1,
                                'price_unit': self.net_amount, 'tax_ids': [Command.set(self.tax_ids.ids)]})]})

    def action_confirm(self):
        self.ensure_one()
        self.check_access('write')
        self._lock()
        self.fund_id._check_spender()
        if self.state in ('paid', 'reviewed'):
            return True  # Idempotent double-click/retry; no second bill/payment.
        receipt_data, mime, digest, key = self._check_document()
        if self.source == 'purchase':
            self.purchase_id.check_access('read')
        # All writes below are atomic even if an upstream caller catches a user-facing error.
        with self.env.cr.savepoint():
            request = self._trusted()
            fund = request.fund_id
            # A row lock alone is insufficient under PostgreSQL REPEATABLE READ.
            # Mutating the shared fund row forces stale concurrent requests to retry
            # with a fresh ledger snapshot rather than spend the same balance twice.
            self.env.cr.execute('SELECT id FROM hopland_petty_cash_fund WHERE id = %s FOR UPDATE', [fund.id])
            fund.invalidate_recordset()
            fund.write({'balance_epoch': fund.balance_epoch + 1})
            method = fund._payment_method()
            limit = fund.per_payment_limit
            if limit and self.currency_id.compare_amounts(self.amount, limit) > 0:
                raise UserError(_('This payment exceeds your delegated per-payment limit. Ask Accounting.'))
            balance = fund._ledger_balance(self.date)
            if self.currency_id.compare_amounts(self.amount, balance) > 0:
                raise UserError(_('Insufficient petty cash: available %(balance).2f, requested %(amount).2f.',
                                  balance=balance, amount=self.amount))
            # Serialize vendor reference checks across different funds as well.
            self.env.cr.execute('SELECT id FROM res_partner WHERE id = %s FOR UPDATE',
                                [self.partner_id.commercial_partner_id.id])
            duplicate = request.search(['|', ('duplicate_key', '=', key),
                '&', ('company_id', '=', self.company_id.id), ('receipt_hash', '=', digest)], limit=1)
            if duplicate:
                raise UserError(_('This vendor reference or receipt file already has a confirmed petty cash payment.'))
            bill = request._bill_for_payment()
            self.env.cr.execute('SELECT id FROM account_move WHERE id = %s FOR UPDATE', [bill.id])
            bill.invalidate_recordset()
            if bill.company_id != self.company_id or bill.currency_id != self.currency_id or bill.move_type != 'in_invoice':
                raise UserError(_('The bill must be a vendor bill in this company and currency.'))
            if bill.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError(_('The bill vendor does not match.'))
            if bill.state not in ('draft', 'posted'):
                raise UserError(_('The bill is cancelled.'))
            if bill.ref and bill.ref.strip().lower() != self.vendor_reference.strip().lower():
                raise UserError(_('The vendor reference must match the selected bill.'))
            if bill.state == 'draft':
                if self.currency_id.compare_amounts(self.amount, bill.amount_total):
                    raise UserError(_('The receipt amount must equal the draft bill total, including tax.'))
                bill.write({'invoice_date': self.invoice_date, 'date': self.date, 'ref': self.vendor_reference.strip()})
                bill.action_post()
            if self.currency_id.compare_amounts(self.amount, bill.amount_residual):
                raise UserError(_('This workflow pays the full outstanding bill balance. Check the amount or ask Accounting to process a partial payment.'))
            payable = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
            if len(payable.account_id) != 1:
                raise UserError(_('The bill must have one payable account.'))
            payment = request.env['account.payment'].create({
                'company_id': self.company_id.id, 'journal_id': fund.journal_id.id,
                'payment_method_line_id': method.id, 'payment_type': 'outbound', 'partner_type': 'supplier',
                'partner_id': bill.partner_id.id, 'currency_id': self.currency_id.id,
                'amount': self.amount, 'date': self.date, 'memo': self.purpose,
                'destination_account_id': payable.account_id.id, 'invoice_ids': [Command.set(bill.ids)],
            })
            payment.action_post()
            if not payment.move_id or payment.move_id.state != 'posted':
                raise UserError(_('The payment did not create a posted accounting entry. Accounting must check the journal.'))
            cash_lines = payment.move_id.line_ids.filtered(lambda line: line.account_id == fund.cash_account_id)
            if self.currency_id.compare_amounts(-sum(cash_lines.mapped('balance')), self.amount):
                raise UserError(_('The posted payment did not reduce the correct cash account. No changes were saved.'))
            payment_payable = payment.move_id.line_ids.filtered(lambda line: line.account_id == payable.account_id)
            (payable | payment_payable).filtered(lambda line: not line.reconciled).reconcile()
            bill.invalidate_recordset(['amount_residual'])
            if not self.currency_id.is_zero(bill.amount_residual):
                raise UserError(_('The bill could not be fully reconciled. No changes were saved.'))
            name = request.env['ir.sequence'].next_by_code('hopland.petty.cash.payment') or f'PC/{self.id}'
            request.write({'name': name, 'state': 'paid', 'bill_id': bill.id, 'payment_id': payment.id,
                           'bill_display': bill.name, 'payment_display': payment.name,
                           'duplicate_key': key, 'receipt_hash': digest, 'posted_by': self.env.uid,
                           'posted_at': fields.Datetime.now()})
            attachment = request.env['ir.attachment'].create({'name': self.receipt_filename,
                'raw': receipt_data, 'mimetype': mime, 'res_model': 'account.move', 'res_id': bill.id})
            body = Markup('<p>%s</p>') % _('Petty cash %(ref)s confirmed by %(user)s; fund: %(fund)s.',
                ref=name, user=self.env.user.name, fund=fund.name)
            bill.message_post(body=body, attachment_ids=attachment.ids)
            request.message_post(body=body)
            request.activity_schedule('hopland_petty_cash.activity_review', user_id=fund.reviewer_id.id,
                summary=_('Review petty cash payment %s', name), date_deadline=fields.Date.context_today(self))
        self.invalidate_recordset()
        return True

    def action_review(self):
        self.check_access('write')
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Accounting access is required.'))
        for request in self.sorted('id'):
            request._lock()
            if request.state == 'reviewed':
                continue
            if request.state != 'paid':
                raise UserError(_('Confirm the payment before reviewing it.'))
            trusted = request._trusted()
            trusted.write({'state': 'reviewed', 'reviewed_by': self.env.uid, 'reviewed_at': fields.Datetime.now()})
            trusted.activity_feedback(['hopland_petty_cash.activity_review'], feedback=_('Reviewed; no second payment created.'))
        return True

    def action_open_bill(self):
        self.ensure_one()
        self.check_access('read')
        self.bill_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.bill_id.id, 'view_mode': 'form'}

    def action_open_payment(self):
        self.ensure_one()
        self.check_access('read')
        self.payment_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': 'account.payment', 'res_id': self.payment_id.id, 'view_mode': 'form'}

    @api.model
    def _configure_menu(self):
        parent = self.env.ref('hopland_birthday_pos.party_accounting_menu').parent_id or self.env.ref('account.menu_finance')
        self.env.ref('hopland_petty_cash.menu_accounting').write({'parent_id': parent.id})
