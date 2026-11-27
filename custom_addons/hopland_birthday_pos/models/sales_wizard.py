from datetime import timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class SalesPartyWizard(models.TransientModel):
    _name = 'hopland.party.sales.wizard'
    _description = 'New party reservation from Sales'
    _check_company_auto = True

    request_uuid = fields.Char(default=lambda self: str(uuid4()), required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Branch', required=True, default=lambda self: self.env.company)
    config_id = fields.Many2one('pos.config', string='Reception register', required=True, check_company=True)
    package_id = fields.Many2one('hopland.birthday.package', required=True, check_company=True)
    additional_room_ids = fields.Many2many('hopland.birthday.room', string='Additional rooms', check_company=True)
    room_id = fields.Many2one('hopland.birthday.room', required=True, check_company=True)
    event_kind = fields.Selection([('birthday', 'Birthday'), ('special', 'Special party')], default='birthday', required=True)
    child_name = fields.Char(string='Child / event name', required=True)
    child_age = fields.Integer(string='Turning age')
    partner_id = fields.Many2one('res.partner', string='Parent / customer', check_company=True)
    parent_name = fields.Char(string='New customer name')
    phone = fields.Char(required=True)
    email = fields.Char()
    children = fields.Integer(required=True, default=10)
    adults = fields.Integer(default=0)
    start = fields.Datetime(required=True, default=lambda self: fields.Datetime.now() + timedelta(days=1))
    stop = fields.Datetime(compute='_compute_stop', string='End time')
    booking_timezone = fields.Char(related='config_id.hopland_birthday_timezone')
    service_ids = fields.Many2many('hopland.birthday.service', string='Included services')
    extra_ids = fields.Many2many('product.product', string='Paid extras')
    allowed_extra_ids = fields.Many2many(related='package_id.extra_product_ids')
    discount = fields.Float(string='Package discount %', default=0)
    notes = fields.Text(string='Special requests / preparation details')
    currency_id = fields.Many2one(related='config_id.currency_id')
    amount_total = fields.Monetary(string='Total', readonly=True)
    minimum_deposit = fields.Monetary(string='Required deposit', readonly=True)
    quoted = fields.Boolean(default=False, readonly=True)

    @api.depends('start', 'package_id.duration_hours')
    def _compute_stop(self):
        for w in self:
            w.stop = w.start + timedelta(hours=w.package_id.duration_hours) if w.start and w.package_id else False

    @api.onchange('company_id')
    def _onchange_company(self):
        self.config_id = False
        self.package_id = False
        self.room_id = False
        self.additional_room_ids = False

    @api.onchange('room_id')
    def _onchange_primary_room(self):
        self.additional_room_ids -= self.room_id

    @api.onchange('config_id', 'package_id', 'partner_id', 'children', 'discount', 'extra_ids', 'company_id')
    def _invalidate_quote(self):
        self.quoted = False
        self.amount_total = 0
        self.minimum_deposit = 0

    @api.onchange('package_id')
    def _onchange_package(self):
        self.service_ids = self.package_id.included_service_ids
        self.extra_ids = False
        self.children = self.package_id.min_children or 10
        self.discount = 0

    @api.onchange('partner_id')
    def _onchange_partner(self):
        self.phone = self.partner_id.phone or ''
        self.email = self.partner_id.email or ''

    def _payload(self):
        self.ensure_one()
        config = self.env['hopland.birthday.booking']._sales_config(self.config_id.id)
        if config.company_id != self.company_id:
            raise UserError(_('The register must belong to the selected branch.'))
        zone = ZoneInfo(config.hopland_birthday_timezone or 'Asia/Riyadh')
        def local(value):
            return value.replace(tzinfo=timezone.utc).astimezone(zone).strftime('%Y-%m-%dT%H:%M:%S') if value else ''
        return {'request_uuid': self.request_uuid, 'package_id': self.package_id.id,
                'room_id': self.room_id.id, 'additional_room_ids': self.additional_room_ids.ids, 'partner_id': self.partner_id.id,
                'parent_name': self.parent_name, 'phone': self.phone, 'email': self.email or '',
                'child_name': self.child_name, 'age': self.child_age,
                'children': self.children, 'adults': self.adults,
                'start': local(self.start), 'stop': local(self.stop),
                'service_ids': self.service_ids.ids, 'extra_ids': self.extra_ids.ids,
                'discount': self.discount, 'notes': self.notes or '',
                'expected_total': self.amount_total, 'event_kind': self.event_kind}

    def action_quote(self):
        self.ensure_one()
        payload = self._payload()
        Booking = self.env['hopland.birthday.booking']
        config = Booking._sales_config(self.config_id.id)
        package = Booking._get_package(config, self.package_id.id)
        partner = Booking._partner(config, payload)
        quote = Booking._quotation(config, package, payload, partner)[0]
        self.write({'quoted': True, 'amount_total': quote.amount_total,
                    'minimum_deposit': config.currency_id.round(quote.amount_total * package.minimum_deposit_percent / 100)})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('New party reservation')}

    def action_reserve(self):
        self.ensure_one()
        if not self.quoted:
            raise UserError(_('Click Calculate price before saving the reservation.'))
        result = self.env['hopland.birthday.booking'].reserve_from_sales(self.config_id.id, self._payload())
        return {'type': 'ir.actions.act_window', 'name': _('Party reservation'),
                'res_model': 'hopland.birthday.booking', 'res_id': result['id'],
                'view_mode': 'form', 'target': 'current'}
