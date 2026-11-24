from collections import defaultdict

from markupsafe import Markup
from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError


def receipt_event(move):
    """Only completed physical movements across the supplier boundary qualify."""
    if move.state != 'done' or move.quantity <= 0:
        return None
    source, destination = move.location_id.usage, move.location_dest_id.usage
    if source == 'supplier' and destination != 'supplier':
        return 'receipt'
    if destination == 'supplier' and source != 'supplier':
        return 'return'
    return None


class PartyReceiptReview(models.Model):
    _name = 'hopland.party.receipt.review'
    _description = 'Party purchase receipt review'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'received_at desc, id desc'
    _check_company_auto = True
    _mail_post_access = 'read'

    name = fields.Char(required=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    booking_id = fields.Many2one('hopland.birthday.booking', required=True,
                                 readonly=True, check_company=True, ondelete='restrict')
    # Source pointers support traceability and bill matching. Accountants use the
    # snapshots below without being granted access to stock or purchasing records.
    purchase_id = fields.Many2one('purchase.order', required=True, readonly=True,
                                  check_company=True, ondelete='restrict')
    picking_id = fields.Many2one('stock.picking', required=True, readonly=True,
                                 check_company=True, ondelete='restrict')
    purchase_reference = fields.Char(required=True, readonly=True)
    receipt_reference = fields.Char(required=True, readonly=True)
    supplier_name = fields.Char(required=True, readonly=True)
    supplier_id = fields.Many2one('res.partner', required=True, readonly=True)
    received_at = fields.Datetime(readonly=True)
    received_items = fields.Text(readonly=True)
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    purchase_total = fields.Monetary(string='Full PO total at receipt', readonly=True)
    event = fields.Selection([('receipt', 'Goods received'), ('return', 'Supplier return')],
                             required=True, readonly=True)
    state = fields.Selection([('pending', 'To review'), ('reviewed', 'Reviewed')],
                             default='pending', required=True, readonly=True, tracking=True)
    review_notes = fields.Text(tracking=True)
    reviewed_by = fields.Many2one('res.users', readonly=True)
    reviewed_at = fields.Datetime(readonly=True)
    notified_user_ids = fields.Many2many('res.users', readonly=True, copy=False)
    _source_unique = models.Constraint('unique(picking_id, purchase_id, event)',
                                       'This receipt already has an Accounting review.')

    def _lock_review(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM hopland_party_receipt_review WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['state', 'notified_user_ids'])

    def write(self, vals):
        if not self.env.su:
            self.check_access('write')
            if not self.env.user.has_group('account.group_account_user') or set(vals) - {'review_notes'}:
                raise AccessError(_('Only accountants may edit review notes. Use Mark reviewed to finish.'))
        return super().write(vals)

    def _notify_accountants(self):
        for review in self.sudo().sorted('id'):
            review._lock_review()
            if review.state != 'pending':
                continue
            recipients = review.booking_id._department_users('account.group_account_user')
            for user in recipients - review.notified_user_ids:
                summary = (_('Goods received — review supplier bill: %s', review.purchase_reference)
                           if review.event == 'receipt' else
                           _('Supplier return — review credit: %s', review.purchase_reference))
                note = Markup('<p>%s</p><p>%s</p><p>%s</p><p>%s</p>') % (
                    _('Reservation: %s. Supplier: %s. Receipt: %s.',
                      review.booking_id.name, review.supplier_name, review.receipt_reference),
                    _('Full purchase order total: %s %s. This is not the value of a partial receipt.',
                      review.purchase_total, review.currency_id.name),
                    review.received_items or '',
                    _('Check the supplier document and match the purchase order in Accounting. '
                      'No bill, credit note, journal entry or payment was created by this task.'))
                review.activity_schedule('hopland_birthday_pos.activity_party_receipt_review',
                    user_id=user.id, summary=summary, note=note,
                    date_deadline=fields.Date.context_today(review))
                review.write({'notified_user_ids': [Command.link(user.id)]})

    def action_mark_reviewed(self):
        self.check_access('write')
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Accounting access is required.'))
        for review in self.sorted('id'):
            review._lock_review()
            if review.state == 'reviewed':
                continue
            review.sudo().write({'state': 'reviewed', 'reviewed_by': self.env.user.id,
                                 'reviewed_at': fields.Datetime.now()})
            review.sudo().activity_feedback(
                ['hopland_birthday_pos.activity_party_receipt_review'],
                feedback=_('Reviewed by %s. This does not post or pay a vendor bill.', self.env.user.name))
        return True

    def action_vendor_bills(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Accounting access is required.'))
        # No sudo on accounting documents. Only bills/credits actually matched
        # to this PO appear, respecting native account.move company rules.
        return {'type': 'ir.actions.act_window', 'name': _('Matched vendor bills / credits'),
                'res_model': 'account.move', 'view_mode': 'list,form',
                'domain': [('move_type', 'in', ['in_invoice', 'in_refund']),
                           ('company_id', '=', self.company_id.id),
                           ('invoice_line_ids.purchase_line_id.order_id', '=', self.purchase_id.id)],
                'context': {'default_move_type': 'in_invoice',
                            'default_partner_id': self.supplier_id.id,
                            'default_company_id': self.company_id.id,
                            'create': False}}

    @api.model
    def _configure_menu_parent(self):
        # Preserve the administrator's fix from Invoicing to the actual
        # Enterprise Accounting root. Never reset it on a subsequent upgrade.
        bookings = self.env.ref('hopland_birthday_pos.party_accounting_menu')
        parent = bookings.parent_id or self.env.ref('account.menu_finance')
        if not bookings.parent_id:
            bookings.write({'parent_id': parent.id})
        self.env.ref('hopland_birthday_pos.party_receipt_review_menu').write({'parent_id': parent.id})


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        result = super()._action_done()
        self._create_hopland_receipt_reviews()
        return result

    def _create_hopland_receipt_reviews(self):
        """Private: used after native validation or by the upgrade backfill.

        One review per completed transfer / PO / direction. Partial deliveries
        and returns are distinct events; retries never create duplicate tasks.
        """
        Review = self.env['hopland.party.receipt.review'].sudo()
        for picking in self.sudo().sorted('id'):
            if picking.state != 'done':
                continue
            self.env.cr.execute('SELECT id FROM stock_picking WHERE id = %s FOR UPDATE', [picking.id])
            grouped = defaultdict(list)
            for move in picking.move_ids:
                event = receipt_event(move)
                line = move.purchase_line_id or move.origin_returned_move_id.purchase_line_id
                order = line.order_id
                booking = order.hopland_booking_id
                if (event and booking and picking.company_id == order.company_id == booking.company_id):
                    grouped[(order, event)].append(move)
            for (order, event), moves in grouped.items():
                review = Review.search([('picking_id', '=', picking.id),
                                        ('purchase_id', '=', order.id), ('event', '=', event)], limit=1)
                if not review:
                    items = '\n'.join('%s: %s %s' % (m.product_id.display_name, m.quantity,
                                                     m.uom_id.name) for m in moves)
                    review = Review.create({
                        'name': '%s / %s' % (picking.name, order.name),
                        'company_id': picking.company_id.id, 'booking_id': order.hopland_booking_id.id,
                        'purchase_id': order.id, 'picking_id': picking.id,
                        'purchase_reference': order.name, 'receipt_reference': picking.name,
                        'supplier_name': order.partner_id.display_name, 'supplier_id': order.partner_id.id,
                        'received_at': picking.date_done, 'received_items': items,
                        'currency_id': order.currency_id.id, 'purchase_total': order.amount_total,
                        'event': event,
                    })
                    review.message_post(body=_('Created from completed transfer %s for purchase order %s.',
                                               picking.name, order.name))
                review._notify_accountants()


class BirthdayReceiptReviews(models.Model):
    _inherit = 'hopland.birthday.booking'
    receipt_review_ids = fields.One2many('hopland.party.receipt.review', 'booking_id', readonly=True)
