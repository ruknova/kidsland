"""Run with stdlib unittest. Tests actual methods with small ORM substitutes.
This is not a substitute for the supplied Odoo integration tests.
"""
import ast
import importlib.util
import pathlib
import sys
import types
import unittest
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'hopland_birthday_pos'

class UserError(Exception): pass
class AccessError(Exception): pass
class ValidationError(Exception): pass

class API:
    model = staticmethod(lambda f: f)
    constrains = staticmethod(lambda *a: lambda f: f)
    onchange = staticmethod(lambda *a: lambda f: f)
    depends = staticmethod(lambda *a: lambda f: f)

class Fields:
    class Date:
        context_today = staticmethod(lambda record: '2026-11-22')
    class Datetime:
        def __init__(self, *a, **kw): pass
        now = staticmethod(lambda: datetime(2026, 11, 22))
    def __getattr__(self, name): return lambda *a, **kw: None

odoo = types.ModuleType('odoo')
odoo.api = API
odoo.fields = Fields()
odoo.models = types.SimpleNamespace(Model=object, TransientModel=object, Constraint=lambda *a: None)
odoo.Command = types.SimpleNamespace(set=lambda x: x)
odoo._ = lambda text, *args: text % args if args else text
sys.modules['odoo'] = odoo
exc = types.ModuleType('odoo.exceptions')
exc.AccessError, exc.UserError, exc.ValidationError = AccessError, UserError, ValidationError
sys.modules['odoo.exceptions'] = exc

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'models' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

D = load('departments')
W = load('sales_wizard')

class Rec:
    def __init__(self, **kw): self.__dict__.update(kw)
    def ensure_one(self): pass
    def sudo(self): return self
    def write(self, vals): self.__dict__.update(vals)
    def activity_schedule(self, *args, **kw): self.activities.append(kw)
    def message_post(self, **kw): pass

class PrepModel:
    def __init__(self, b): self.booking = b; self.created = []
    def sudo(self): return self
    def create(self, vals):
        p = Rec(on_hold=False, activities=[])
        self.created.append(p); self.booking.preparation_ids.append(p); return p

class HandoffTests(unittest.TestCase):
    def make_booking(self):
        b = Rec(id=7, name='BDAY/2026/7', child_name='Omar', state='tentative',
                confirmation_notified=False, notified_paid_amount=0,
                amount_paid=0, balance=1440, preparation_ids=[], activities=[])
        b.currency_id = Rec(name='SAR', compare_amounts=lambda a, c: round(a-c,2))
        b._department_users = lambda group: [Rec(id=12 if group.startswith('purchase') else 13)]
        prep = PrepModel(b); b.env = {'hopland.party.preparation': prep}
        return b, prep

    def test_tentative_has_no_preparation_or_payment_task(self):
        b,p = self.make_booking(); D.BirthdayDepartments._department_handoff(b)
        self.assertEqual(p.created, []); self.assertEqual(b.activities, [])

    def test_confirmation_is_idempotent(self):
        b,p = self.make_booking(); b.state='confirmed'; b.amount_paid=720; b.balance=720
        for _ in range(3): D.BirthdayDepartments._department_handoff(b)
        self.assertEqual(len(p.created),1); self.assertEqual(len(p.created[0].activities),1)
        self.assertEqual(len(b.activities),1)

    def test_balance_payment_notifies_accounting_without_duplicate_prep(self):
        b,p = self.make_booking(); b.state='confirmed'; b.amount_paid=720; b.balance=720
        D.BirthdayDepartments._department_handoff(b)
        b.amount_paid=1440; b.balance=0
        D.BirthdayDepartments._department_handoff(b)
        D.BirthdayDepartments._department_handoff(b)
        self.assertEqual(len(p.created),1); self.assertEqual(len(b.activities),2)
        self.assertEqual(b.notified_paid_amount,1440)

    def test_refund_holds_preparation_and_reconfirmation_reuses_it(self):
        b,p = self.make_booking(); b.state='confirmed'; b.amount_paid=720
        D.BirthdayDepartments._department_handoff(b)
        b.state='tentative'; b.amount_paid=0
        D.BirthdayDepartments._department_handoff(b)
        self.assertTrue(p.created[0].on_hold)
        b.state='confirmed'; b.amount_paid=720
        D.BirthdayDepartments._department_handoff(b)
        self.assertFalse(p.created[0].on_hold); self.assertEqual(len(p.created),1)

    def test_cancelled_has_no_tasks(self):
        b,p=self.make_booking(); b.state='cancelled'; b.amount_paid=720
        D.BirthdayDepartments._department_handoff(b)
        self.assertEqual(p.created,[]); self.assertEqual(b.activities,[])

class AccessTests(unittest.TestCase):
    def config(self, can_sales=True, allowed=True, enabled=True):
        company=object()
        config=Rec(company_id=company, hopland_birthday_enabled=enabled)
        config.check_access=lambda operation: None
        config.exists=lambda:config
        user=Rec(has_group=lambda name:can_sales)
        class Env(dict): pass
        env=Env({'pos.config': Rec(browse=lambda id:config)})
        env.user=user; env.companies=[company] if allowed else []
        return Rec(env=env), config

    def test_sales_config_requires_sales_group(self):
        rec,_=self.config(can_sales=False)
        with self.assertRaises(AccessError): D.BirthdayDepartments._sales_config(rec,1)

    def test_sales_config_rejects_unselected_company(self):
        rec,_=self.config(allowed=False)
        with self.assertRaises(AccessError): D.BirthdayDepartments._sales_config(rec,1)

    def test_sales_config_rejects_disabled_register(self):
        rec,_=self.config(enabled=False)
        with self.assertRaises(UserError): D.BirthdayDepartments._sales_config(rec,1)

    def test_sales_config_does_not_need_open_session(self):
        rec,c=self.config()
        self.assertIs(D.BirthdayDepartments._sales_config(rec,1),c)

    def test_sales_uses_shared_reservation_validator(self):
        config=object(); payload={'event_kind':'special'}
        rec=Rec(_sales_config=lambda id: config,
                _reserve=lambda c,p,source: (c,p,source))
        self.assertEqual(D.BirthdayDepartments.reserve_from_sales(rec,1,payload),(config,payload,'sales'))
        with self.assertRaises(UserError):
            D.BirthdayDepartments.reserve_from_sales(rec,1,{'event_kind':'wrong'})

class TimeTests(unittest.TestCase):
    def test_wizard_converts_utc_to_register_time(self):
        c=Rec(id=4,company_id=10,hopland_birthday_timezone='Asia/Riyadh')
        w=Rec(config_id=c,company_id=10,start=datetime(2026,11,23,14),stop=datetime(2026,11,23,16),
              request_uuid='uuid',package_id=Rec(id=1),room_id=Rec(id=2),partner_id=Rec(id=3),
              parent_name='',phone='0551234567',email='',child_name='Omar',child_age=7,
              children=10,adults=2,service_ids=Rec(ids=[1]),extra_ids=Rec(ids=[2]),
              discount=0,notes='',amount_total=1440,event_kind='birthday')
        w.env={'hopland.birthday.booking':Rec(_sales_config=lambda id:c)}
        p=W.SalesPartyWizard._payload(w)
        self.assertEqual(p['start'],'2026-11-23T17:00:00')
        self.assertEqual(p['stop'],'2026-11-23T19:00:00')
        w.company_id=99
        with self.assertRaises(UserError): W.SalesPartyWizard._payload(w)

class QuoteTests(unittest.TestCase):
    def test_action_quote_accepts_five_value_pricing_result(self):
        # Match the actual pricing-helper return arity, including selected services.
        c = Rec(currency_id=Rec(round=lambda x: round(x, 2)))
        package = Rec(minimum_deposit_percent=50)
        pricing = Rec(_sales_config=lambda id: c, _get_package=lambda c,id: package,
                      _partner=lambda c,p: Rec(id=7),
                      _quotation=lambda *args: (Rec(amount_total=1440), {}, 10, [1,2], [3]))
        wizard = Rec(id=9, _name='hopland.party.sales.wizard',
                     config_id=Rec(id=4), package_id=Rec(id=5),
                     _payload=lambda: {}, env={'hopland.birthday.booking': pricing})
        action = W.SalesPartyWizard.action_quote(wizard)
        self.assertEqual(wizard.amount_total, 1440)
        self.assertEqual(wizard.minimum_deposit, 720)
        self.assertTrue(wizard.quoted)
        self.assertEqual(action['res_id'], 9)

if __name__ == '__main__': unittest.main()
