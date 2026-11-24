"""Share the original module sequence without resetting issued numbers.

The original XML omitted company_id, so Odoo used the installation company.
Because that record is noupdate, an XML-only fix cannot repair existing installs.
"""
from odoo import api


def migrate(cr, version):
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    sequence = env.ref('hopland_birthday_pos.booking_sequence')
    if sequence._name != 'ir.sequence' or sequence.code != 'hopland.birthday.booking':
        raise ValueError('Unexpected Hopland booking sequence configuration; review before upgrading.')
    # Preserve the same record, prefix, padding and current counter. Do not
    # change any separately configured company-specific sequences.
    if sequence.company_id:
        sequence.write({'company_id': False})
