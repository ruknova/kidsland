from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class BirthdayPackage(models.Model):
    _name = 'hopland.birthday.package'
    _description = 'Birthday package'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    product_id = fields.Many2one('product.product', required=True, check_company=True,
                                 domain=[('type', '=', 'service'), ('available_in_pos', '=', True)])
    image_128 = fields.Image(related='product_id.image_128')
    min_children = fields.Integer(default=10, required=True)
    max_children = fields.Integer(default=50, required=True)
    duration_hours = fields.Float(default=2, required=True)
    minimum_deposit_percent = fields.Float(default=50, required=True)
    max_discount_percent = fields.Float(default=10, required=True)
    included_service_ids = fields.One2many('hopland.birthday.service', 'package_id', copy=True)
    extra_product_ids = fields.Many2many('product.product', check_company=True,
                                        domain=[('type', '=', 'service'), ('available_in_pos', '=', True)])
    terms = fields.Text(default='Birthday cake is optional. Party date and time require confirmation. Remaining balance is due before the party.')

    @api.constrains('min_children', 'max_children', 'duration_hours', 'minimum_deposit_percent', 'max_discount_percent', 'product_id', 'extra_product_ids')
    def _check_package(self):
        for p in self:
            if p.min_children < 1 or p.max_children < p.min_children or not 0 < p.duration_hours <= 24:
                raise ValidationError(_('Check the minimum/maximum children and party duration.'))
            if not 0 < p.minimum_deposit_percent <= 100 or not 0 <= p.max_discount_percent <= 100:
                raise ValidationError(_('Deposit must be above zero and up to 100%; discount must be 0–100%.'))
            products = p.product_id | p.extra_product_ids
            if any(prod.type != 'service' or not prod.available_in_pos or not prod.sale_ok or prod.invoice_policy != 'order' for prod in products):
                raise ValidationError(_('Birthday products must be services, available for Sales and POS, invoiced on ordered quantities.'))
            if p.product_id in p.extra_product_ids:
                raise ValidationError(_('The package cannot also be an extra.'))


class BirthdayService(models.Model):
    _name = 'hopland.birthday.service'
    _description = 'Included birthday service'
    _order = 'sequence, id'
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    package_id = fields.Many2one('hopland.birthday.package', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='package_id.company_id', store=True)


class BirthdayRoom(models.Model):
    _name = 'hopland.birthday.room'
    _description = 'Birthday party room'
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    capacity = fields.Integer(default=50, required=True, help='Maximum children. Adults are recorded separately.')
    reservation_lock_version = fields.Integer(default=0, readonly=True, copy=False)
    @api.constrains('capacity')
    def _check_capacity(self):
        if any(r.capacity < 1 for r in self):
            raise ValidationError(_('Room capacity must be positive.'))


class PosConfig(models.Model):
    _inherit = 'pos.config'
    hopland_birthday_enabled = fields.Boolean(string='Birthday reservations')
    hopland_birthday_timezone = fields.Char(default='Asia/Riyadh', string='Birthday booking timezone')


class ProductTemplate(models.Model):
    _inherit = 'product.template'
    hopland_birthday_product = fields.Boolean(compute='_compute_hopland_birthday_product')

    def _compute_hopland_birthday_product(self):
        packages = self.env['hopland.birthday.package'].sudo().search([('product_id.product_tmpl_id', 'in', self.ids)])
        ids = set(packages.product_id.product_tmpl_id.ids)
        for template in self:
            template.hopland_birthday_product = template.id in ids

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['hopland_birthday_product']
