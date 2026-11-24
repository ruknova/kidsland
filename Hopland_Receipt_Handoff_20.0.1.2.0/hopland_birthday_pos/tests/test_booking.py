"""Run in a disposable Odoo database: --test-tags /hopland_birthday_pos.
These integration tests require the full Odoo runtime; not executed by the standalone checks.
"""
from datetime import timedelta
from uuid import uuid4

from odoo import fields, Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon
from odoo.addons.pos_sale.tests.test_pos_sale_flow import PoSSaleSyncCommon


@tagged('post_install', '-at_install')
class TestBirthdayBooking(PoSSaleSyncCommon, TestPointOfSaleHttpCommon):
    def setUp(self):
        super().setUp()
        self.config = self.main_pos_config
        self.config.hopland_birthday_enabled = True
        self.config.open_ui()
        session = self.config.current_session_id
        if session.state == 'opening_control':
            session.set_opening_control(0, 'Birthday test')
        self.customer = self.env['res.partner'].create({'name': 'Birthday test parent', 'phone': '0551234567'})
        tax = self.env['account.tax'].create({
            'name': 'Birthday VAT 15 included', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'price_include_override': 'tax_included',
            'company_id': self.env.company.id,
        })
        self.tax = tax
        def product(name, price):
            return self.env['product.product'].create({'name': name, 'list_price': price, 'type': 'service',
                'available_in_pos': True, 'invoice_policy': 'order', 'taxes_id': [Command.set(tax.ids)]})
        base, cake, photo = product('Birthday package test',99), product('Cake test',150), product('Photo test',300)
        self.package = self.env['hopland.birthday.package'].create({
            'name': 'Birthday test', 'product_id': base.id, 'company_id': self.env.company.id,
            'extra_product_ids': [Command.set((cake|photo).ids)],
            'included_service_ids': [Command.create({'name': 'Party room'})],
        })
        self.room = self.env['hopland.birthday.room'].create({'name': 'Test room', 'company_id': self.env.company.id})
        day = (fields.Datetime.now()+timedelta(days=7)).strftime('%Y-%m-%d')
        self.payload = {'request_uuid':str(uuid4()), 'package_id':self.package.id, 'room_id':self.room.id,
            'partner_id':self.customer.id, 'phone':self.customer.phone, 'child_name':'Omar', 'age':6,
            'children':10, 'adults':2, 'start':day+'T17:00', 'stop':day+'T19:00', 'discount':10,
            'extra_ids':(cake|photo).ids, 'service_ids':self.package.included_service_ids.ids, 'expected_total':1341}
        self.Booking = self.env['hopland.birthday.booking']

    def test_preview_no_records_and_prices(self):
        before = self.env['sale.order'].search_count([])
        quote = self.Booking.preview(self.config.id, self.payload)
        self.assertAlmostEqual(quote['total'],1341)
        self.assertAlmostEqual(quote['minimum_deposit'],670.50)
        self.assertEqual([l['qty'] for l in quote['lines']],[10,1,1])
        self.assertEqual(self.env['sale.order'].search_count([]),before)

    def test_reference_uses_register_company(self):
        other = self.env['res.company'].create({'name': 'Birthday other company'})
        self.env['ir.sequence'].create({
            'name': 'Birthday register test', 'code': 'hopland.birthday.booking',
            'company_id': self.config.company_id.id, 'prefix': 'REGISTER/', 'padding': 5,
        })
        self.env['ir.sequence'].create({
            'name': 'Birthday wrong company test', 'code': 'hopland.birthday.booking',
            'company_id': other.id, 'prefix': 'OTHER/', 'padding': 5,
        })
        reference = self.Booking.with_company(other)._next_reference(self.config)
        self.assertTrue(reference.startswith('REGISTER/'))

    def test_missing_sequence_does_not_create_sale(self):
        sequences = self.env['ir.sequence'].sudo().search([('code', '=', 'hopland.birthday.booking')])
        sequences.write({'active': False})
        before_sales = self.env['sale.order'].search_count([])
        before_bookings = self.Booking.search_count([])
        with self.assertRaisesRegex(UserError, 'No birthday booking sequence'), self.cr.savepoint():
            self.Booking.reserve(self.config.id, self.payload)
        self.assertEqual(self.env['sale.order'].search_count([]), before_sales)
        self.assertEqual(self.Booking.search_count([]), before_bookings)

    def test_shared_sequence_and_matching_sale_reference(self):
        sequence = self.env.ref('hopland_birthday_pos.booking_sequence')
        self.assertFalse(sequence.company_id)
        first = self.Booking.reserve(self.config.id, self.payload)
        booking = self.Booking.browse(first['id'])
        self.assertTrue(booking.name)
        self.assertNotEqual(booking.name, 'New')
        self.assertEqual(booking.name, booking.sale_order_id.origin)
        self.assertEqual(booking.name, booking.sale_order_id.client_order_ref)

    def test_idempotency_and_room_collision(self):
        first = self.Booking.reserve(self.config.id,self.payload)
        second = self.Booking.reserve(self.config.id,self.payload)
        self.assertEqual(first['id'],second['id'])
        with self.assertRaises(UserError), self.cr.savepoint():
            self.Booking.reserve(self.config.id,{**self.payload,'request_uuid':str(uuid4())})
        adjacent = self.Booking.reserve(self.config.id,{**self.payload,'request_uuid':str(uuid4()),
            'start':self.payload['start'][:10]+'T19:00','stop':self.payload['start'][:10]+'T21:00'})
        self.assertNotEqual(first['id'],adjacent['id'])

    def test_reject_invalid_inputs(self):
        for patch in [{'children':9},{'discount':11},{'extra_ids':[9999999]},{'children':float('nan')}]:
            with self.subTest(patch=patch), self.assertRaises(UserError):
                self.Booking.preview(self.config.id,{**self.payload,**patch})
        with self.assertRaises(UserError),self.cr.savepoint():
            self.Booking.reserve(self.config.id,{**self.payload,'expected_total':1})

    def test_checkout_limits_and_exclusive_token(self):
        b = self.Booking.reserve(self.config.id,self.payload)
        with self.assertRaises(UserError):
            self.Booking.checkout(self.config.id,b['id'],str(uuid4()),'deposit',100)
        token = str(uuid4())
        self.Booking.checkout(self.config.id,b['id'],token,'deposit',670.5)
        with self.assertRaises(UserError):
            self.Booking.checkout(self.config.id,b['id'],str(uuid4()),'deposit',670.5)
        self.assertEqual(self.Booking.browse(b['id']).state,'tentative')
        self.assertEqual(self.Booking.browse(b['id']).amount_paid,0)

    def test_native_deposit_then_balance(self):
        b = self.Booking.reserve(self.config.id,self.payload)
        booking = self.Booking.browse(b['id'])
        token = str(uuid4())
        self.Booking.checkout(self.config.id,booking.id,token,'deposit',670.5)
        data = self._prepare_pos_order_data([{
            'product':self.config.down_payment_product_id,'price_unit':670.5,'qty':1,'taxes':self.tax,
            'extra_values':{'sale_order_origin_id':booking.sale_order_id.id,
                'down_payment_details':'[]','extra_tax_data':{'computation_key':'down_payment'}},
        }], partner=self.customer, uuid=token, hopland_booking_uuid=booking.request_uuid)
        self.env['pos.order'].sync_from_ui([data])
        booking.invalidate_recordset()
        self.assertEqual(booking.state,'confirmed')
        self.assertAlmostEqual(booking.amount_paid,670.5)
        self.assertAlmostEqual(booking.balance,670.5)
        # Native settlement imports original lines and deducts the previously received deposit.
        token2 = str(uuid4())
        self.Booking.checkout(self.config.id,booking.id,token2,'full',670.5)
        lines=[]
        for line in booking.sale_order_id.order_line.filtered(lambda l: not l.display_type):
            lines.append({'product':line.product_id,'qty':-1 if line.is_downpayment else line.product_uom_qty,
                'price_unit':line.price_unit,'discount':line.discount,'taxes':line.tax_ids,
                'extra_values':{'sale_order_origin_id':booking.sale_order_id.id,'sale_order_line_id':line.id}})
        data2=self._prepare_pos_order_data(lines,partner=self.customer,uuid=token2,hopland_booking_uuid=booking.request_uuid)
        self.env['pos.order'].sync_from_ui([data2])
        booking.invalidate_recordset()
        self.assertAlmostEqual(booking.amount_paid,1341)
        self.assertAlmostEqual(booking.balance,0)
        self.assertEqual(booking.payment_status,'paid')
