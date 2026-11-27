from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class BirthdayDepartments(models.Model):
    _inherit = 'hopland.birthday.booking'

    source = fields.Selection([('pos', 'Reception / POS'), ('sales', 'Central Sales')],
                              default='pos', required=True, readonly=True, copy=False)
    event_kind = fields.Selection([('birthday', 'Birthday'), ('special', 'Special party')],
                                  default='birthday', required=True, readonly=True)
    salesperson_id = fields.Many2one('res.users', readonly=True)
    preparation_ids = fields.One2many('hopland.party.preparation', 'booking_id', readonly=True)
    confirmation_notified = fields.Boolean(readonly=True, copy=False)
    notified_paid_amount = fields.Monetary(readonly=True, copy=False)

    @api.model
    def _sales_config(self, config_id):
        if not self.env.user.has_group('sales_team.group_sale_salesman'):
            raise AccessError(_('Sales access is required.'))
        config = self.env['pos.config'].browse(int(config_id)).exists()
        if not config:
            raise UserError(_('Select a reception register.'))
        config.check_access('read')
        if config.company_id not in self.env.companies:
            raise AccessError(_('Select this branch in the company switcher first.'))
        if not config.hopland_birthday_enabled:
            raise UserError(_('Enable birthday reservations on this register first.'))
        return config

    @api.model
    def reserve_from_sales(self, config_id, payload):
        config = self._sales_config(config_id)
        if payload.get('event_kind', 'birthday') not in ('birthday', 'special'):
            raise UserError(_('Choose Birthday or Special party.'))
        # Same pricing, validation, overlap guard, sequence and retry handling as POS.
        # Deliberately does not require an open POS session or grant POS cashier access.
        return self._reserve(config, payload, source='sales')

    @api.model
    def sales_arrivals(self, config_id, after_id=None):
        config = self._config(config_id)
        domain = [('config_id', '=', config.id), ('source', '=', 'sales')]
        if after_id is None:
            latest = self.search(domain, order='id desc', limit=1)
            # Opening a register also announces waiting Sales reservations.
            waiting = self.search(domain + [('state', '=', 'tentative')], order='id desc', limit=10)
            return {'cursor': latest.id or 0, 'bookings': [
                {'id': b.id, 'reference': b.name, 'child': b.child_name} for b in waiting]}
        records = self.search(domain + [('id', '>', max(int(after_id), 0))], order='id', limit=50)
        return {'cursor': records[-1].id if records else int(after_id), 'bookings': [
            {'id': b.id, 'reference': b.name, 'child': b.child_name}
            for b in records if b.state != 'cancelled']}

    def _department_users(self, group_xmlid):
        self.ensure_one()
        group = self.env.ref(group_xmlid)
        # Use implied groups too; exclude inactive/portal and unrelated companies.
        return self.env['res.users'].sudo().search([
            ('active', '=', True), ('share', '=', False),
            ('all_group_ids', 'in', group.ids),
            ('company_ids', 'in', [self.company_id.id]),
        ])

    def _department_handoff(self):
        self.ensure_one()
        booking = self.sudo()
        if booking.state == 'cancelled':
            return
        if booking.state == 'confirmed' and not booking.confirmation_notified:
            preparation = self.env['hopland.party.preparation'].sudo().create({'booking_id': booking.id})
            recipients = booking._department_users('purchase.group_purchase_user')
            note = Markup('<p>%s</p><p>%s</p>') % (
                _('Deposit requirement met. Check stock and arrange only missing supplies/services.'),
                _('%s — %s. Open the preparation record for the date, room, services and requests.',
                  booking.name, booking.child_name))
            for user in recipients:
                preparation.activity_schedule('mail.mail_activity_data_todo',
                    user_id=user.id, summary=_('Prepare party: %s', booking.name),
                    note=note, date_deadline=fields.Date.context_today(booking))
            booking.write({'confirmation_notified': True})
            booking.message_post(body=_('Deposit requirement met. Purchasing preparation created for %s user(s).', len(recipients)))
        # Refunds can put a confirmed booking back below its deposit requirement.
        for prep in booking.preparation_ids:
            hold = booking.state not in ('confirmed', 'completed')
            if prep.on_hold != hold:
                prep.sudo().write({'on_hold': hold})
        if booking.currency_id.compare_amounts(booking.amount_paid, booking.notified_paid_amount) != 0:
            for user in booking._department_users('account.group_account_user'):
                booking.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                    summary=_('Review party payment: %s', booking.name),
                    note=Markup('<p>%s</p><p>%s</p>') % (
                        _('Received: %s %s. Remaining: %s %s.', booking.amount_paid,
                          booking.currency_id.name, booking.balance, booking.currency_id.name),
                        _('Payment was updated in POS. Review its related orders and session posting.')))
            booking.write({'notified_paid_amount': booking.amount_paid})


class PartyPreparation(models.Model):
    _name = 'hopland.party.preparation'
    _description = 'Party preparation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start, id'
    _check_company_auto = True
    _mail_post_access = 'read'

    booking_id = fields.Many2one('hopland.birthday.booking', required=True, readonly=True, ondelete='restrict')
    name = fields.Char(related='booking_id.name', store=True)
    company_id = fields.Many2one(related='booking_id.company_id', store=True)
    child_name = fields.Char(related='booking_id.child_name', string='Child / event')
    event_kind = fields.Selection(related='booking_id.event_kind')
    start = fields.Datetime(related='booking_id.start', store=True)
    stop = fields.Datetime(related='booking_id.stop')
    timezone = fields.Char(related='booking_id.timezone')
    room_id = fields.Many2one(related='booking_id.room_id')
    additional_room_ids = fields.Many2many(related='booking_id.additional_room_ids')
    children = fields.Integer(related='booking_id.children')
    adults = fields.Integer(related='booking_id.adults')
    included_services = fields.Text(related='booking_id.included_services')
    extras = fields.Text(related='booking_id.extras')
    notes = fields.Text(related='booking_id.notes', string='Customer requests')
    state = fields.Selection([('pending', 'To prepare'), ('progress', 'Preparing'), ('ready', 'Ready')],
                              default='pending', required=True, tracking=True)
    on_hold = fields.Boolean(default=False, readonly=True, tracking=True)
    preparation_notes = fields.Text(string='Stock check / purchasing notes', tracking=True)
    purchase_ids = fields.Many2many('purchase.order',
                                   compute='_compute_purchases', string='RFQs / purchase orders')
    _booking_unique = models.Constraint('unique(booking_id)', 'Preparation already exists for this reservation.')

    def _compute_purchases(self):
        for prep in self:
            # Use caller rights: sales/accounting do not gain purchase-document access.
            prep.purchase_ids = self.env['purchase.order'].search([('hopland_booking_id', '=', prep.booking_id.id)])

    def write(self, vals):
        if not self.env.su:
            if not self.env.user.has_group('purchase.group_purchase_user'):
                raise AccessError(_('Purchasing access is required to update preparation.'))
            if set(vals) - {'state', 'preparation_notes'}:
                raise AccessError(_('Only preparation status and purchasing notes can be changed.'))
            self.check_access('write')
            if 'state' in vals and any(p.on_hold or p.booking_id.state not in ('confirmed', 'completed') for p in self):
                raise UserError(_('This preparation is on hold. Review the booking payment first.'))
        return super().write(vals)

    def action_new_rfq(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('purchase.group_purchase_user'):
            raise AccessError(_('Purchasing access is required.'))
        if self.on_hold or self.booking_id.state not in ('confirmed', 'completed'):
            raise UserError(_('The reservation must be confirmed before purchasing.'))
        return {'type': 'ir.actions.act_window', 'name': _('Request for Quotation'),
                'res_model': 'purchase.order', 'view_mode': 'form', 'target': 'current',
                'context': {'default_company_id': self.company_id.id,
                            'default_hopland_booking_id': self.booking_id.id,
                            'default_origin': self.booking_id.name}}


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    hopland_booking_id = fields.Many2one('hopland.birthday.booking', string='Party reservation',
                                        check_company=True, ondelete='restrict', copy=False)

    @api.constrains('hopland_booking_id', 'company_id')
    def _check_hopland_booking(self):
        for order in self.filtered('hopland_booking_id'):
            order.hopland_booking_id.check_access('read')
            if order.hopland_booking_id.state not in ('confirmed', 'completed'):
                raise ValidationError(_('Purchasing requires a confirmed party reservation.'))

    def button_confirm(self):
        self._check_hopland_booking()
        return super().button_confirm()
