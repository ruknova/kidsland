"""Odoo integration tests; run only against a disposable test database.
Requires the full Odoo 20 runtime and the POS test fixtures.
"""
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError
from .test_booking import TestBirthdayBooking


class TestPartyDepartments(TestBirthdayBooking):
    def setUp(self):
        super().setUp()
        def user(login, groups):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'company_id': self.env.company.id,
                'company_ids': [Command.set(self.env.company.ids)],
                'group_ids': [Command.set([self.env.ref(g).id for g in ['base.group_user'] + groups])],
            })
        self.sales_user = user('party_sales_test', ['sales_team.group_sale_salesman_all_leads'])
        self.purchase_user = user('party_purchase_test', ['purchase.group_purchase_user'])
        self.account_user = user('party_account_test', ['account.group_account_user'])

    def test_sales_without_pos_can_reserve_and_retry(self):
        sales = self.Booking.with_user(self.sales_user)
        self.assertFalse(self.sales_user.has_group('point_of_sale.group_pos_user'))
        first = sales.reserve_from_sales(self.config.id, self.payload)
        second = sales.reserve_from_sales(self.config.id, self.payload)
        self.assertEqual(first['id'], second['id'])
        booking = sales.browse(first['id'])
        self.assertEqual(booking.source, 'sales')
        self.assertEqual(booking.salesperson_id, self.sales_user)
        self.assertFalse(booking.preparation_ids)
        self.assertEqual(booking.state, 'tentative')
        self.assertEqual(self.Booking.sales_arrivals(self.config.id, 0)['bookings'][0]['id'], booking.id)
        with self.assertRaises(AccessError):
            sales.checkout(self.config.id, booking.id, str(uuid4()), 'deposit', 670.5)

    def test_sales_booking_when_register_is_closed(self):
        self.config.current_session_id.write({'state': 'closed'})
        sales = self.Booking.with_user(self.sales_user)
        result = sales.reserve_from_sales(self.config.id, self.payload)
        self.assertEqual(sales.browse(result['id']).state, 'tentative')

    def test_non_sales_cannot_use_sales_endpoint(self):
        for user in (self.purchase_user, self.account_user):
            with self.subTest(user=user.login), self.assertRaises(AccessError):
                self.Booking.with_user(user).reserve_from_sales(self.config.id, self.payload)

    def test_cross_company_sales_rejected(self):
        branch = self.env['res.company'].create({'name': 'Other inaccessible party branch'})
        # Branch check is tested using a config stub so no unrelated POS setup is required.
        self.sales_user.write({'company_ids': [Command.set(branch.ids)], 'company_id': branch.id})
        sales = self.Booking.with_user(self.sales_user).with_context(allowed_company_ids=branch.ids)
        with self.assertRaises(AccessError):
            sales.reserve_from_sales(self.config.id, self.payload)

    def test_sales_wizard_price_and_creation(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        start = datetime.fromisoformat(self.payload['start']).replace(tzinfo=ZoneInfo(self.config.hopland_birthday_timezone or 'Asia/Riyadh')).astimezone(timezone.utc).replace(tzinfo=None)
        wizard = self.env['hopland.party.sales.wizard'].with_user(self.sales_user).create({
            'company_id': self.env.company.id, 'config_id': self.config.id,
            'package_id': self.package.id, 'room_id': self.room.id, 'partner_id': self.customer.id,
            'phone': self.customer.phone, 'child_name': 'Sales demo', 'children': 10,
            'start': start, 'discount': 10,
            'service_ids': [Command.set(self.package.included_service_ids.ids)],
            'extra_ids': [Command.set(self.package.extra_product_ids.ids)],
        })
        with self.assertRaises(UserError):
            wizard.action_reserve()
        wizard.action_quote()
        self.assertAlmostEqual(wizard.amount_total, 1341)
        result = wizard.action_reserve()
        self.assertEqual(self.Booking.browse(result['res_id']).source, 'sales')

    def test_handoff_is_once_and_roles_are_limited(self):
        result = self.Booking.reserve(self.config.id, self.payload)
        booking = self.Booking.browse(result['id'])
        # Exercise the handoff with a confirmed balance; the inherited native-payment
        # test separately verifies that confirmation only follows validated POS payment.
        booking.sudo().write({'state': 'confirmed'})
        booking._department_handoff()
        booking._department_handoff()
        self.assertEqual(len(booking.preparation_ids), 1)
        prep = booking.preparation_ids
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'hopland.party.preparation'), ('res_id', '=', prep.id),
            ('user_id', '=', self.purchase_user.id),
        ])
        self.assertEqual(len(activities), 1)
        prep.with_user(self.purchase_user).write({'state': 'progress', 'preparation_notes': 'Check balloons'})
        with self.assertRaises(AccessError):
            prep.with_user(self.sales_user).write({'state': 'ready'})
        with self.assertRaises(AccessError):
            prep.with_user(self.purchase_user).write({'booking_id': booking.id})
        booking.write({'state': 'tentative'})
        booking._department_handoff()
        self.assertTrue(prep.on_hold)
        with self.assertRaises(UserError):
            prep.with_user(self.purchase_user).action_new_rfq()

    def test_native_deposit_then_balance(self):
        super().test_native_deposit_then_balance()
        booking = self.Booking.search([('request_uuid', '=', self.payload['request_uuid'])])
        self.assertEqual(len(booking.preparation_ids), 1)
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'hopland.birthday.booking'), ('res_id', '=', booking.id),
            ('user_id', '=', self.account_user.id),
        ])
        self.assertEqual(len(activities), 2)
        booking._refresh_status()
        self.assertEqual(len(booking.preparation_ids), 1)
        self.assertEqual(self.env['mail.activity'].search_count([
            ('res_model', '=', 'hopland.birthday.booking'), ('res_id', '=', booking.id),
            ('user_id', '=', self.account_user.id),
        ]), 2)
