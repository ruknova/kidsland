from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'
    hopland_booking_uuid = fields.Char(copy=False, index=True)

    @api.model
    def _process_order(self, order, existing_order):
        booking = self.env['hopland.birthday.booking']
        is_refund = bool(order.get('is_refund')) or float(order.get('amount_total', 0)) < 0
        token = order.get('hopland_booking_uuid')
        if token and not is_refund and order.get('state') != 'cancel':
            booking = booking.search([('request_uuid', '=', token)], limit=1)
            if not booking:
                raise UserError(_('Birthday reservation not found.'))
            booking._lock()
            session = self.env['pos.session'].browse(order.get('session_id'))
            if session.config_id != booking.config_id or order.get('uuid') != booking.checkout_uuid:
                raise UserError(_('This birthday checkout is no longer active. Reopen the booking from Birthday Reservations.'))
            if booking.state in ('cancelled', 'completed'):
                raise UserError(_('This birthday reservation is closed.'))
        result = super()._process_order(order, existing_order)
        saved = self.browse(result)
        if saved.state in ('paid', 'done', 'invoiced') and not is_refund:
            linked = self.env['hopland.birthday.booking'].search([('sale_order_id', 'in', saved.lines.sale_order_origin_id.ids)])
            if linked and not booking:
                raise UserError(_('Collect birthday payments through the Birthday Reservations button.'))
            if booking:
                if saved.partner_id != booking.partner_id or saved.company_id != booking.company_id:
                    raise UserError(_('The payment customer or branch does not match the reservation.'))
                if any(l.sale_order_origin_id != booking.sale_order_id for l in saved.lines):
                    raise UserError(_('Keep birthday payments separate from other POS purchases.'))
                if any(p.payment_method_id.type == 'pay_later' for p in saved.payment_ids):
                    raise UserError(_('A birthday deposit must be received by cash or a configured payment method, not Customer Account.'))
                actual = saved._get_order_tax_totals()['total_amount_currency']
                if booking.currency_id.compare_amounts(actual, booking.checkout_amount) != 0:
                    raise UserError(_('The POS amount changed. Return to the birthday booking and prepare the payment again.'))
        return result

    @api.model
    def sync_from_ui(self, orders):
        result = super().sync_from_ui(orders)
        ids = [o['id'] for o in result.get('pos.order', [])]
        saved = self.browse(ids)
        sale_orders = saved.lines.sale_order_origin_id | saved.lines.refunded_orderline_id.sale_order_origin_id
        bookings = self.env['hopland.birthday.booking'].sudo().search([('sale_order_id', 'in', sale_orders.ids)])
        for booking in bookings:
            booking._lock()
            matching = saved.filtered(lambda o: o.uuid == booking.checkout_uuid and o.state in ('paid', 'done', 'invoiced'))
            if matching:
                booking.write({'checkout_uuid': False, 'checkout_amount': 0, 'checkout_mode': False, 'checkout_user_id': False})
            booking._refresh_status()
        return result
