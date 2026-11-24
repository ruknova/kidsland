from odoo import api


def migrate(cr, version):
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    # Do not create new tasks/notifications for historic demo payments on upgrade.
    for booking in env['hopland.birthday.booking'].search([]):
        booking.write({
            'confirmation_notified': booking.state in ('confirmed', 'completed'),
            'notified_paid_amount': booking.amount_paid,
        })
