"""Executable handoff checks using ORM substitutes, not full Odoo tests."""
import unittest
import test_workflow as common

common.odoo.Command.link = lambda value: (4, value)
class NativePicking:
    def _action_done(self):
        self.native_completed = True
        return 'native result'
common.odoo.models.Model = NativePicking
R = common.load('receipt_handoff')


class Records(list):
    @property
    def ids(self): return [r.id for r in self]
    def sudo(self): return self
    def sorted(self, key): return Records(sorted(self, key=lambda r: getattr(r, key)))
    def __sub__(self, other): return Records(r for r in self if r.id not in other.ids)


class Record(common.Rec):
    def __iter__(self): return iter([self])
    def sorted(self, key): return Records([self])
    def _lock_review(self): self.locked = True
    def check_access(self, operation):
        if not self.allowed: raise common.AccessError('company access denied')
    def write(self, vals):
        vals = dict(vals)
        for op, uid in vals.pop('notified_user_ids', []):
            self.notified_user_ids.append(common.Rec(id=uid))
        super().write(vals)
    def _notify_accountants(self): return R.PartyReceiptReview._notify_accountants(self)
    def activity_feedback(self, *a, **kw): self.finished = True


class ReviewStore:
    def __init__(self, env, fixtures): self.env=env; self.fixtures=fixtures; self.records=[]
    def sudo(self): return self
    def search(self, domain, limit=1):
        for record in self.records:
            if all(getattr(record, field).id == value if field.endswith('_id')
                   else getattr(record, field) == value for field, op, value in domain):
                return record
        return None
    def create(self, vals):
        values=dict(vals)
        for key in ('booking_id','currency_id','purchase_id','picking_id','company_id','supplier_id'):
            values[key]=self.fixtures[key][values[key]]
        record=Record(id=len(self.records)+1, state='pending', notified_user_ids=Records(),
                      activities=[], env=self.env, allowed=True, **values)
        self.records.append(record)
        return record


class HandoffTests(unittest.TestCase):
    def test_hook_runs_after_native_completion_and_preserves_return(self):
        class Picking(R.StockPicking):
            def _create_hopland_receipt_reviews(self):
                self.called_after_completion = self.native_completed
        picking = Picking()
        self.assertEqual(picking._action_done(), 'native result')
        self.assertTrue(picking.called_after_completion)

    def setUp(self):
        self.company=Record(id=1)
        self.users=Records([Record(id=10),Record(id=11)])
        self.booking=Record(id=4,name='BDAY/2026/00004',company_id=self.company,
                            _department_users=lambda group:self.users)
        self.currency=Record(id=3,name='SAR')
        self.supplier=Record(id=7,display_name='<Cake Supplier>')
        self.order=Record(id=2,name='P00002',hopland_booking_id=self.booking,
                          company_id=self.company, partner_id=self.supplier,
                          currency_id=self.currency,amount_total=172.50)
        self.move=Record(state='done', quantity=1, location_id=Record(usage='supplier'),
                         location_dest_id=Record(usage='internal'),
                         purchase_line_id=Record(order_id=self.order),
                         product_id=Record(display_name='Cake <script>'),uom_id=Record(name='Units'))
        self.picking=Record(id=5,name='YAS/IN/00001',state='done',company_id=self.company,
                            move_ids=[self.move],date_done='2026-11-22')
        class Env(dict): pass
        self.env=Env()
        self.env.cr=Record(execute=lambda *args:None)
        self.env.user=Record(id=10,name='Accountant',has_group=lambda group:True)
        fixtures={'booking_id':{4:self.booking},'currency_id':{3:self.currency},
                  'purchase_id':{2:self.order},'picking_id':{5:self.picking},
                  'company_id':{1:self.company},'supplier_id':{7:self.supplier}}
        self.store=ReviewStore(self.env,fixtures)
        self.env['hopland.party.receipt.review']=self.store
        self.pickings=Records([self.picking]);self.pickings.env=self.env

    def run_handoff(self): R.StockPicking._create_hopland_receipt_reviews(self.pickings)

    def test_completed_receipt_has_snapshot_and_one_task_per_accountant(self):
        self.run_handoff(); review=self.store.records[0]
        self.assertEqual(review.purchase_reference,'P00002')
        self.assertEqual(review.booking_id.id,4)
        self.assertEqual(review.purchase_total,172.50)
        self.assertIn('1 Units',review.received_items)
        self.assertEqual(len(review.activities),2)
        self.assertIn('&lt;script&gt;',str(review.activities[0]['note']))
        self.assertNotIn('<script>',str(review.activities[0]['note']))

    def test_retries_do_not_duplicate_review_or_tasks(self):
        for _ in range(3):self.run_handoff()
        self.assertEqual(len(self.store.records),1)
        self.assertEqual(len(self.store.records[0].activities),2)

    def test_backorder_is_separate_review_with_actual_quantity(self):
        self.move.quantity=0.5;self.run_handoff()
        second=Record(**{**self.picking.__dict__,'id':6,'name':'YAS/IN/00002'})
        self.store.fixtures['picking_id'][6]=second
        self.pickings.append(second);self.run_handoff()
        self.assertEqual(len(self.store.records),2)
        self.assertIn('0.5 Units',self.store.records[1].received_items)

    def test_unfinished_cancelled_zero_and_internal_moves_do_not_notify(self):
        for state in ('draft','assigned','cancel'):
            self.picking.state=state;self.run_handoff()
        self.picking.state='done';self.move.quantity=0;self.run_handoff()
        self.move.quantity=1;self.move.location_id.usage='internal';self.run_handoff()
        self.assertEqual(self.store.records,[])

    def test_non_party_order_does_not_notify(self):
        self.order.hopland_booking_id=None;self.run_handoff()
        self.assertEqual(self.store.records,[])

    def test_mismatched_company_does_not_leak(self):
        self.order.company_id=Record(id=8);self.run_handoff()
        self.assertEqual(self.store.records,[])

    def test_return_uses_original_purchase_line_and_credit_task(self):
        self.move.origin_returned_move_id=Record(purchase_line_id=self.move.purchase_line_id)
        self.move.purchase_line_id=None
        self.move.location_id.usage='internal';self.move.location_dest_id.usage='supplier'
        self.run_handoff();review=self.store.records[0]
        self.assertEqual(review.event,'return')
        self.assertIn('review credit',review.activities[0]['summary'])

    def test_missing_accountant_leaves_review_and_retry_can_assign(self):
        self.users.clear();self.run_handoff()
        self.assertEqual(len(self.store.records),1)
        self.assertEqual(self.store.records[0].activities,[])
        self.users.append(Record(id=12));self.run_handoff()
        self.assertEqual(len(self.store.records[0].activities),1)

    def test_completed_review_does_not_notify_again(self):
        self.run_handoff();review=self.store.records[0]
        R.PartyReceiptReview.action_mark_reviewed(review)
        self.assertEqual(review.state,'reviewed');self.assertTrue(review.finished)
        self.run_handoff();self.assertEqual(len(review.activities),2)

    def test_review_completion_requires_accounting_and_company_access(self):
        self.run_handoff();review=self.store.records[0]
        self.env.user.has_group=lambda group:False
        with self.assertRaises(common.AccessError):R.PartyReceiptReview.action_mark_reviewed(review)
        self.env.user.has_group=lambda group:True;review.allowed=False
        with self.assertRaises(common.AccessError):R.PartyReceiptReview.action_mark_reviewed(review)

    def test_bill_action_filters_exact_po_and_company(self):
        self.run_handoff();action=R.PartyReceiptReview.action_vendor_bills(self.store.records[0])
        self.assertIn(('company_id','=',1),action['domain'])
        self.assertIn(('invoice_line_ids.purchase_line_id.order_id','=',2),action['domain'])
        self.assertFalse(action['context']['create'])

    def test_snapshots_and_state_cannot_be_forged_by_write(self):
        self.run_handoff();review=self.store.records[0];self.env.su=False
        for vals in ({'state':'reviewed'},{'purchase_total':0},{'company_id':8}):
            with self.assertRaises(common.AccessError):R.PartyReceiptReview.write(review,vals)

    def test_menu_parent_preserves_admin_correction(self):
        target=Record(parent_id=Record(id=99))
        child=Record()
        self.env.ref=lambda xmlid:target if xmlid.endswith('party_accounting_menu') else child
        R.PartyReceiptReview._configure_menu_parent(Record(env=self.env))
        self.assertEqual(child.parent_id,99)


if __name__=='__main__':unittest.main()
