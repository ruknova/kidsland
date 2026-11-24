import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Catch up only completed supplier transfers linked to party purchases.
    # Includes P00002/YAS/IN/00001 in the demo; does not recreate a receipt.
    orders = env['purchase.order'].search([('hopland_booking_id', '!=', False)])
    pickings = env['stock.picking'].search([
        ('state', '=', 'done'), ('move_ids.purchase_line_id.order_id', 'in', orders.ids),
    ], order='id')
    pickings._create_hopland_receipt_reviews()
    _logger.info('Hopland receipt handoff: examined %s completed party transfers.', len(pickings))
