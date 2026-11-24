import logging
from odoo import Command

_logger = logging.getLogger(__name__)
SERVICES = [
    'Party room and chairs', 'Basic balloon decoration', 'Sound system',
    'Cartoon character appearance', 'Two hours of play, excluding the Creators Zone',
    'Cake display stand and cake-cutting utensils', "Children's meal",
]


def post_init_hook(env):
    """Connect exact existing demo records; never replace prices, taxes or posted orders."""
    products = env['product.product'].with_context(lang='en_US').search([
        ('name', '=', 'Birthday Standard – Al Yasmin – Demo'), ('active', '=', True)])
    if len(products) != 1:
        _logger.warning('Hopland birthday: exact demo product not unique/found; configure a package manually.')
        return
    configs = env['pos.config'].search([('company_id.name', '=', 'Hopland – Al Yasmin')])
    if not configs:
        _logger.warning('Hopland birthday: Al Yasmin POS not found; configure a package manually.')
        return
    for company in configs.company_id:
        product = products.with_company(company)
        if product.company_id and product.company_id.id not in (company.id, company.root_id.id):
            continue
        extras = env['product.product'].with_context(lang='en_US').search([
            ('name', 'in', ['Birthday Photographer – Demo', 'Birthday Cake – Demo']),
            ('company_id', 'in', [False, company.id, company.root_id.id]), ('available_in_pos', '=', True)])
        existing = env['hopland.birthday.package'].search([('product_id', '=', product.id), ('company_id', '=', company.id)])
        if not existing:
            env['hopland.birthday.package'].with_company(company).create({
                'name': 'Birthday Standard', 'company_id': company.id, 'product_id': product.id,
                'extra_product_ids': [Command.set(extras.ids)],
                'included_service_ids': [Command.create({'name': n, 'sequence': i}) for i, n in enumerate(SERVICES)],
            })
        if not env['hopland.birthday.room'].search_count([('company_id', '=', company.id)]):
            env['hopland.birthday.room'].create({'name': 'Al Yasmin — Demo Party Room', 'company_id': company.id, 'capacity': 50})
        configs.filtered(lambda c: c.company_id == company).write({'hopland_birthday_enabled': True})
