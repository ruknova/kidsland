"""Read-only verification, executed through Odoo shell by the Windows installer."""
module = env['ir.module.module'].sudo().search([('name', '=', 'hopland_birthday_pos')], limit=1)
if module.state != 'installed' or module.latest_version != '20.0.1.0.1':
    raise RuntimeError('The birthday module upgrade to 20.0.1.0.1 was not applied.')
sequence = env.ref('hopland_birthday_pos.booking_sequence')
if sequence._name != 'ir.sequence' or sequence.code != 'hopland.birthday.booking':
    raise RuntimeError('The booking sequence is missing or has an unexpected code.')
if sequence.company_id or not sequence.active:
    raise RuntimeError('The booking sequence must be active and shared across companies.')
print('Sequence ID:', sequence.id, '| Prefix:', sequence.prefix, '| Shared: yes')
print('HOPLAND_REFERENCE_FIX_OK')
# Do not call next_by_code: verification must not consume reference numbers.
