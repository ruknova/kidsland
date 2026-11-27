from datetime import timedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError

from .validation import number, time_range, uuid_value


class BirthdayBooking(models.Model):
    _name = 'hopland.birthday.booking'
    _description = 'Hopland birthday reservation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start desc, id desc'
    _mail_post_access = 'read'
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, copy=False, default='New')
    request_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    config_id = fields.Many2one('pos.config', required=True, readonly=True, check_company=True)
    package_id = fields.Many2one('hopland.birthday.package', required=True, readonly=True, check_company=True)
    additional_room_ids = fields.Many2many('hopland.birthday.room', string='Additional rooms', check_company=True, readonly=True, copy=False)
    room_id = fields.Many2one('hopland.birthday.room', required=True, readonly=True, check_company=True)
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, check_company=True)
    phone = fields.Char(required=True, readonly=True)
    email = fields.Char(readonly=True)
    child_name = fields.Char(required=True, readonly=True)
    child_age = fields.Integer(readonly=True)
    children = fields.Integer(required=True, readonly=True)
    adults = fields.Integer(readonly=True)
    start = fields.Datetime(required=True, readonly=True, index=True)
    stop = fields.Datetime(required=True, readonly=True)
    timezone = fields.Char(default='Asia/Riyadh', required=True, readonly=True)
    included_services = fields.Text(readonly=True)
    extras = fields.Text(readonly=True)
    notes = fields.Text(readonly=True)
    sale_order_id = fields.Many2one('sale.order', required=True, readonly=True, check_company=True)
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    amount_total = fields.Monetary(required=True, readonly=True)
    minimum_deposit = fields.Monetary(required=True, readonly=True)
    amount_paid = fields.Monetary(compute='_compute_payment')
    balance = fields.Monetary(compute='_compute_payment')
    payment_status = fields.Selection([('unpaid', 'Unpaid'), ('partial', 'Deposit received'), ('paid', 'Paid')], compute='_compute_payment')
    state = fields.Selection([('tentative', 'Tentative'), ('confirmed', 'Confirmed'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='tentative', required=True, readonly=True, tracking=True)
    checkout_uuid = fields.Char(readonly=True, copy=False)
    checkout_amount = fields.Monetary(readonly=True)
    checkout_mode = fields.Selection([('deposit', 'Deposit'), ('full', 'Full / remaining balance')], readonly=True)
    checkout_user_id = fields.Many2one('res.users', readonly=True)
    _request_unique = models.Constraint('unique(request_uuid)', 'This reservation request already exists.')

    def _paid_pos_lines(self):
        self.ensure_one()
        origins = self.sale_order_id.sudo().pos_order_line_ids
        lines = origins | origins.refund_orderline_ids
        return lines.filtered(lambda l: l.order_id.state in ('paid', 'done', 'invoiced'))

    @api.depends('sale_order_id.pos_order_line_ids.order_id.state', 'sale_order_id.pos_order_line_ids.price_subtotal_incl',
                 'sale_order_id.pos_order_line_ids.refund_orderline_ids.order_id.state',
                 'sale_order_id.pos_order_line_ids.refund_orderline_ids.price_subtotal_incl', 'amount_total')
    def _compute_payment(self):
        for booking in self:
            paid = sum(-line.price_subtotal_incl if line.order_id.is_refund else line.price_subtotal_incl for line in booking._paid_pos_lines())
            booking.amount_paid = booking.currency_id.round(paid)
            booking.balance = max(booking.currency_id.round(booking.amount_total - paid), 0)
            booking.payment_status = ('paid' if booking.currency_id.compare_amounts(paid, booking.amount_total) >= 0 else
                                      'partial' if booking.currency_id.compare_amounts(paid, 0) > 0 else 'unpaid')

    @api.model
    def _config(self, config_id, require_open=True):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('POS access is required.'))
        config = self.env['pos.config'].browse(int(config_id)).exists()
        if not config:
            raise UserError(_('Point of Sale not found.'))
        config.check_access('read')
        if config.company_id not in self.env.companies:
            raise AccessError(_('Switch to this branch before booking.'))
        if not config.hopland_birthday_enabled:
            raise UserError(_('Enable Birthday reservations in the POS configuration.'))
        if require_open and config.current_session_id.state != 'opened':
            raise UserError(_('Open the POS session before making a reservation.'))
        return config

    @api.model
    def _get_package(self, config, package_id):
        package = self.env['hopland.birthday.package'].search([
            ('id', '=', int(package_id)), ('company_id', '=', config.company_id.id), ('active', '=', True)], limit=1)
        if not package:
            raise UserError(_('Select an available birthday package for this branch.'))
        package._check_package()
        return package

    @api.model
    def catalog(self, config_id):
        config = self._config(config_id)
        packages = self.env['hopland.birthday.package'].search([('company_id', '=', config.company_id.id)])
        rooms = self.env['hopland.birthday.room'].search([('company_id', '=', config.company_id.id)])
        return {
            'branch': config.company_id.name, 'timezone': config.hopland_birthday_timezone or 'Asia/Riyadh',
            'currency': config.currency_id.name,
            'packages': [{
                'id': p.id, 'name': p.name, 'product_id': p.product_id.id,
                'template_id': p.product_id.product_tmpl_id.id,
                'min_children': p.min_children, 'max_children': p.max_children, 'duration': p.duration_hours,
                'deposit_percent': p.minimum_deposit_percent, 'max_discount': p.max_discount_percent,
                'services': [{'id': s.id, 'name': s.name} for s in p.included_service_ids],
                'extras': [{'id': e.id, 'name': e.name, 'template_id': e.product_tmpl_id.id} for e in p.extra_product_ids],
                'terms': p.terms or '',
            } for p in packages],
            'rooms': [{'id': r.id, 'name': r.name, 'capacity': r.capacity} for r in rooms],
        }

    @api.model
    def customers(self, config_id, query):
        config = self._config(config_id)
        query = str(query or '').strip()[:80]
        if len(query) < 3:
            return []
        partners = self.env['res.partner'].search([
            ('company_id', 'in', [False, config.company_id.id, config.company_id.root_id.id]),
            '|', ('name', 'ilike', query), ('phone', 'ilike', query)], limit=8)
        return [{'id': p.id, 'name': p.name, 'phone': p.phone or '', 'email': p.email or ''} for p in partners]

    @api.model
    def _partner(self, config, payload, create=False):
        if payload.get('partner_id'):
            partner = self.env['res.partner'].browse(int(payload['partner_id'])).exists()
            if not partner:
                raise UserError(_('Customer not found.'))
            partner.check_access('read')
            if partner.company_id and partner.company_id.id not in (config.company_id.id, config.company_id.root_id.id):
                raise AccessError(_('Customer belongs to another company.'))
            return partner
        if not create:
            # A new customer's public pricing preview uses the branch contact only in-memory.
            return config.company_id.partner_id
        name = str(payload.get('parent_name', '')).strip()[:150]
        phone = str(payload.get('phone', '')).strip()[:40]
        if not name or len(phone) < 7:
            raise UserError(_('Enter the parent name and a valid phone number.'))
        return self.env['res.partner'].with_company(config.company_id).create({
            'name': name, 'phone': phone, 'email': str(payload.get('email', '')).strip()[:150] or False,
            'customer_rank': 1,
        })

    @api.model
    def _sale_values(self, config, package, payload, partner):
        try:
            children = number(payload.get('children'), 'Number of children', package.min_children, package.max_children, True)
            discount = number(payload.get('discount', 0), 'Package discount', 0, package.max_discount_percent)
            extra_ids = {int(i) for i in payload.get('extra_ids', [])}
            service_ids = {int(i) for i in payload.get('service_ids', [])}
        except (ValueError, TypeError) as exc:
            raise UserError(str(exc)) from None
        if not extra_ids.issubset(set(package.extra_product_ids.ids)) or not service_ids.issubset(set(package.included_service_ids.ids)):
            raise UserError(_('Some selected services are not available for this package.'))
        extras = package.extra_product_ids.filtered(lambda p: p.id in extra_ids)
        services = package.included_service_ids.filtered(lambda s: s.id in service_ids)
        lines = [Command.create({'product_id': package.product_id.id, 'product_uom_qty': children, 'discount': discount})]
        lines += [Command.create({'product_id': p.id, 'product_uom_qty': 1, 'discount': 0}) for p in extras]
        pricelist = config.pricelist_id or partner.with_company(config.company_id).property_product_pricelist
        if not pricelist or pricelist.currency_id != config.currency_id:
            raise UserError(_('Configure a POS pricelist in the same currency as this register.'))
        vals = {'partner_id': partner.id, 'company_id': config.company_id.id,
                'pricelist_id': pricelist.id, 'order_line': lines}
        if config.default_fiscal_position_id:
            vals['fiscal_position_id'] = config.default_fiscal_position_id.id
        return vals, children, extras, services

    @api.model
    def _quotation(self, config, package, payload, partner):
        vals, children, extras, services = self._sale_values(config, package, payload, partner)
        # Native sale pricing and tax computations; preview never creates persistent records.
        quotation = self.env['sale.order'].sudo().with_company(config.company_id).new(vals)
        return quotation, vals, children, extras, services

    @api.model
    def preview(self, config_id, payload):
        config = self._config(config_id)
        package = self._get_package(config, payload.get('package_id'))
        partner = self._partner(config, payload)
        quotation, _, _, _, _ = self._quotation(config, package, payload, partner)
        return {'total': quotation.amount_total, 'tax': quotation.amount_tax, 'untaxed': quotation.amount_untaxed,
                'minimum_deposit': config.currency_id.round(quotation.amount_total * package.minimum_deposit_percent / 100),
                'lines': [{'name': l.product_id.name, 'product_id': l.product_id.id,
                           'qty': l.product_uom_qty, 'total': l.price_total} for l in quotation.order_line]}

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM hopland_birthday_booking WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    @api.model
    def _next_reference(self, config):
        # Sequence lookup uses the active company even under sudo. Use the
        # register company, with the shared module sequence as Odoo's fallback.
        reference = self.env['ir.sequence'].sudo().with_company(config.company_id).next_by_code(
            'hopland.birthday.booking')
        if not reference:
            raise UserError(_(
                'No birthday booking sequence is available for this register. '
                'Ask an administrator to upgrade Hopland Birthday Reservations '
                'and check its booking sequence configuration.'
            ))
        return reference

    @api.model
    def reserve(self, config_id, payload):
        return self._reserve(self._config(config_id), payload)

    @api.model
    def _reserve(self, config, payload, source='pos'):
        try:
            request = uuid_value(payload.get('request_uuid'))
        except ValueError as exc:
            raise UserError(str(exc)) from None
        # Serialize retries before looking for the unique request, including concurrent tabs.
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['hopland-birthday:' + request])
        existing = self.search([('request_uuid', '=', request)], limit=1)
        if existing:
            if existing.config_id != config:
                raise AccessError(_('Reservation belongs to another register.'))
            return existing._summary()
        package = self._get_package(config, payload.get('package_id'))
        timezone = config.hopland_birthday_timezone or 'Asia/Riyadh'
        try:
            start, stop = time_range(payload.get('start'), payload.get('stop'), timezone)
            age = number(payload.get('age', 0), 'Age', 0, 18, True)
            adults = number(payload.get('adults', 0), 'Accompanying adults', 0, 100, True)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        if start < fields.Datetime.now() - timedelta(minutes=5):
            raise UserError(_('Choose a future party time.'))
        if abs((stop - start).total_seconds() / 3600 - package.duration_hours) > 0.001:
            raise UserError(_('This package includes %s hours. Adjust the party end time.', package.duration_hours))
        child = str(payload.get('child_name', '')).strip()[:150]
        phone = str(payload.get('phone', '')).strip()[:40]
        if not child or len(phone) < 7:
            raise UserError(_('Enter the birthday child name and parent phone number.'))
        room = self.env['hopland.birthday.room'].search([
            ('id', '=', int(payload.get('room_id') or 0)), ('company_id', '=', config.company_id.id)], limit=1)
        if not room:
            raise UserError(_('Select an available party room.'))
        selected = payload.get('additional_room_ids', [])
        if not isinstance(selected, list) or any(type(value) is not int or value <= 0 for value in selected):
            raise UserError(_('Select valid additional rooms.'))
        room_ids = sorted(set(selected) | {room.id})
        rooms = self.env['hopland.birthday.room'].search([
            ('id', 'in', room_ids), ('active', '=', True), ('company_id', '=', config.company_id.id)], order='id')
        if rooms.ids != room_ids:
            raise UserError(_('Select active rooms from the reservation branch.'))
        # Update the room guard, rather than merely locking it. Under PostgreSQL's
        # repeatable-read isolation, a competing reservation must retry with a fresh
        # snapshot to see the first booking before checking for overlapping slots.
        for selected_room in rooms:
            self.env.cr.execute('UPDATE hopland_birthday_room SET reservation_lock_version = COALESCE(reservation_lock_version, 0) + 1 WHERE id = %s', [selected_room.id])
        rooms.invalidate_recordset(['reservation_lock_version'])
        if self.sudo().search_count(['|', ('room_id', 'in', room_ids), ('additional_room_ids', 'in', room_ids), ('state', '!=', 'cancelled'),
                                    ('start', '<', fields.Datetime.to_string(stop)), ('stop', '>', fields.Datetime.to_string(start))]):
            raise UserError(_('A selected room already has a reservation at that time. Choose another time or room.'))
        partner = self._partner(config, payload, create=True)
        quotation, vals, children, extras, services = self._quotation(config, package, payload, partner)
        if children > min(rooms.mapped('capacity')):
            raise UserError(_('For a group visiting each selected room, the smallest room holds %s children.', min(rooms.mapped('capacity'))))
        try:
            shown_total = number(payload.get('expected_total'), 'Displayed total', 0.01)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        if config.currency_id.compare_amounts(quotation.amount_total, shown_total) != 0:
            raise UserError(_('The price changed. Refresh the price summary and try again.'))
        reference = self._next_reference(config)
        notes = str(payload.get('notes', '')).strip()[:2000]
        selected_names = '\n'.join(services.mapped('name'))
        detail = (f'{reference} | {child}, age {age}\n'
                  f'{payload["start"]} – {payload["stop"]} ({timezone}) | {", ".join(rooms.mapped("name"))}\n'
                  f'{children} children, {adults} adults | Contact: {phone}\n'
                  f'Selected included services:\n{selected_names}\nNotes: {notes}')
        vals.update({'origin': reference, 'client_order_ref': reference,
                     'order_line': vals['order_line'] + [Command.create({'display_type': 'line_note', 'name': detail})]})
        if source == 'sales':
            vals['user_id'] = self.env.uid
        sale = self.env['sale.order'].sudo().with_company(config.company_id).create(vals)
        if config.currency_id.compare_amounts(sale.amount_total, shown_total) != 0:
            raise UserError(_('The saved price differs from the preview. Refresh and try again.'))
        booking = self.sudo().with_company(config.company_id).create({
            'source': source, 'salesperson_id': self.env.uid,
            'event_kind': payload.get('event_kind', 'birthday'),
            'name': reference, 'request_uuid': request, 'company_id': config.company_id.id, 'config_id': config.id,
            'package_id': package.id, 'room_id': room.id, 'additional_room_ids': [Command.set((rooms - room).ids)], 'partner_id': partner.id, 'phone': phone,
            'email': str(payload.get('email', '')).strip()[:150], 'child_name': child, 'child_age': age,
            'children': children, 'adults': adults, 'start': start, 'stop': stop, 'timezone': timezone,
            'included_services': selected_names, 'extras': '\n'.join(extras.mapped('name')),
            'notes': notes, 'sale_order_id': sale.id, 'currency_id': config.currency_id.id,
            'amount_total': sale.amount_total,
            'minimum_deposit': config.currency_id.round(sale.amount_total * package.minimum_deposit_percent / 100),
        })
        booking.message_post(body=_('Tentative reservation created by %s (%s). No payment has been recorded yet.', self.env.user.display_name, source))
        return booking._summary()

    def _summary(self):
        self.ensure_one()
        self.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])
        return {'id': self.id, 'reference': self.name, 'child': self.child_name,
                'parent': self.partner_id.name, 'phone': self.phone, 'room': ', '.join((self.room_id | self.additional_room_ids).mapped('name')),
                'start': fields.Datetime.to_string(self.start), 'stop': fields.Datetime.to_string(self.stop),
                'timezone': self.timezone, 'children': self.children, 'state': self.state,
                'total': self.amount_total, 'paid': self.amount_paid, 'balance': self.balance,
                'minimum_deposit': self.minimum_deposit, 'sale_order_id': self.sale_order_id.id,
                'checkout_uuid': self.checkout_uuid or False, 'request_uuid': self.request_uuid,
                'checkout_amount': self.checkout_amount, 'checkout_mode': self.checkout_mode}

    @api.model
    def list_bookings(self, config_id, query=''):
        config = self._config(config_id)
        domain = [('company_id', '=', config.company_id.id), ('config_id', '=', config.id)]
        if query:
            q = str(query)[:80]
            domain += ['|', '|', '|', ('name', 'ilike', q), ('child_name', 'ilike', q), ('phone', 'ilike', q), ('partner_id.name', 'ilike', q)]
        bookings = self.search(domain, limit=50, order='start desc')
        bookings._refresh_status()
        return [b._summary() for b in bookings]

    def _refresh_status(self):
        for booking in self.sorted('id'):
            booking._lock()
            booking.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])
            if booking.state not in ('cancelled', 'completed'):
                state = 'confirmed' if booking.currency_id.compare_amounts(booking.amount_paid, booking.minimum_deposit) >= 0 else 'tentative'
                if booking.state != state:
                    booking.sudo().write({'state': state})
            booking._department_handoff()

    @api.model
    def checkout(self, config_id, booking_id, order_uuid, mode='deposit', amount=0):
        config = self._config(config_id)
        booking = self.browse(int(booking_id)).exists()
        if not booking:
            raise UserError(_('Reservation not found.'))
        booking.check_access('read')
        if booking.config_id != config:
            raise AccessError(_('Use the register that created this booking.'))
        booking._lock()
        if booking.state in ('cancelled', 'completed'):
            raise UserError(_('This reservation is closed.'))
        booking.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])
        try:
            order_uuid = uuid_value(order_uuid)
            amount = number(amount, 'Payment amount', 0.01)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        if booking.checkout_uuid and booking.checkout_uuid != order_uuid:
            raise UserError(_('A payment is already open for this reservation. Resume its existing POS order.'))
        if mode not in ('deposit', 'full'):
            raise UserError(_('Choose deposit or full payment.'))
        if mode == 'deposit' and not config.down_payment_product_id:
            raise UserError(_('Configure the POS down payment product before collecting a deposit.'))
        if booking.currency_id.compare_amounts(amount, booking.balance) > 0:
            raise UserError(_('Payment exceeds the remaining balance.'))
        if mode == 'full' and booking.currency_id.compare_amounts(amount, booking.balance) != 0:
            raise UserError(_('Reload the booking to pay its current balance.'))
        if mode == 'deposit' and booking.currency_id.compare_amounts(amount, booking.balance) == 0:
            raise UserError(_('Use Pay in Full for the whole balance.'))
        minimum = max(booking.minimum_deposit - booking.amount_paid, 0)
        if booking.currency_id.compare_amounts(amount, minimum) < 0:
            raise UserError(_('The deposit must reach %s %s to confirm this booking.', booking.minimum_deposit, booking.currency_id.name))
        sale = booking.sale_order_id.sudo()
        if sale.state == 'cancel' or booking.currency_id.compare_amounts(sale.amount_total, booking.amount_total) != 0:
            raise UserError(_('The linked sales order changed. Ask a manager to review it.'))
        # Prevent a draft payment on another terminal from changing the native amount_unpaid.
        drafts = sale.pos_order_line_ids.order_id.filtered(lambda o: o.state == 'draft' and o.uuid != order_uuid)
        if drafts:
            raise UserError(_('Another unpaid POS order already uses this reservation. Finish or remove that order first.'))
        booking.sudo().write({'checkout_uuid': order_uuid, 'checkout_amount': amount,
                             'checkout_mode': mode, 'checkout_user_id': self.env.uid})
        result = booking._summary()
        result.update({'amount': amount, 'mode': mode, 'order_uuid': order_uuid})
        return result

    @api.model
    def cancel_tentative(self, config_id, booking_id):
        config = self._config(config_id)
        booking = self.browse(int(booking_id)).exists()
        booking.check_access('read')
        if booking.config_id != config:
            raise AccessError(_('Wrong register.'))
        booking._lock()
        booking.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])
        if booking.checkout_uuid or not booking.currency_id.is_zero(booking.amount_paid):
            raise UserError(_('A payment is open or money has been received. Ask a manager to review it.'))
        if booking.state != 'tentative':
            raise UserError(_('Only unpaid tentative reservations can be cancelled here.'))
        booking.sudo().write({'state': 'cancelled'})
        booking.sale_order_id.sudo().action_cancel()
        return True

    def action_release_checkout(self):
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('A POS manager must release an abandoned checkout.'))
        for booking in self:
            booking.check_access('read')
            booking._lock()
            orders = self.env['pos.order'].search([('uuid', '=', booking.checkout_uuid)]) if booking.checkout_uuid else self.env['pos.order']
            if orders.filtered(lambda o: o.state not in ('draft', 'cancel') or o.payment_ids):
                raise UserError(_('This checkout has payment data. Resolve it in POS before releasing it.'))
            if orders.filtered(lambda o: o.state == 'draft'):
                raise UserError(_('Remove the unpaid order from POS and sync it before releasing the checkout.'))
            booking.sudo().write({'checkout_uuid': False, 'checkout_amount': 0, 'checkout_mode': False, 'checkout_user_id': False})
            booking.sudo().message_post(body=_('Abandoned checkout released by %s. Its old checkout token can no longer be paid.', self.env.user.display_name))
        return True

    def action_complete(self):
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('A POS manager must complete the reservation.'))
        for booking in self:
            booking.check_access('read')
            booking._lock()
            booking.invalidate_recordset(['amount_paid', 'balance', 'payment_status'])
            if booking.state != 'confirmed' or not booking.currency_id.is_zero(booking.balance) or booking.checkout_uuid:
                raise UserError(_('Complete a confirmed, fully paid reservation after its party.'))
            if booking.stop > fields.Datetime.now():
                raise UserError(_('The party has not ended yet.'))
            booking.sudo().write({'state': 'completed'})
        return True
