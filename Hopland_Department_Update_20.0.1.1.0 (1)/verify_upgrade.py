module = env['ir.module.module'].search([('name', '=', 'hopland_birthday_pos')], limit=1)
assert module.state == 'installed', 'Birthday module is not installed'
assert module.latest_version == '20.0.1.1.0', module.latest_version
for xmlid in ['party_sales_wizard_action', 'party_sales_new', 'party_purchasing_menu', 'party_accounting_menu']:
    assert env.ref('hopland_birthday_pos.' + xmlid), xmlid
assert 'source' in env['hopland.birthday.booking']._fields
assert 'hopland_booking_id' in env['purchase.order']._fields
assert env['ir.module.module'].search([('name', '=', 'purchase_stock'), ('state', '=', 'installed')])
print('HOPLAND_DEPARTMENTS_UPGRADE_OK')
print('Sales form, purchasing preparation and accounting menu are installed.')
print('No reservation, payment, RFQ or user was created by verification.')
env.cr.rollback()
