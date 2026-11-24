"""Standalone regression checks. Does not replace the Odoo integration tests."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'hopland_birthday_pos'


class ConfigurationError(Exception):
    pass


def reference_method():
    tree = ast.parse((MODULE / 'models/booking.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BirthdayBooking')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_next_reference')
    method.decorator_list = []
    scope = {'UserError': ConfigurationError, '_': lambda message: message}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual reference method>', 'exec'), scope)
    return scope['_next_reference']


def migration_function(env):
    tree = ast.parse((MODULE / 'migrations/20.0.1.0.1/post-booking-sequence.py').read_text())
    tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom)]
    scope = {'api': SimpleNamespace(SUPERUSER_ID=1, Environment=lambda *args: env)}
    exec(compile(tree, '<actual migration>', 'exec'), scope)
    return scope['migrate']


class SequenceModel:
    """Minimal company-filtering contract used by Odoo next_by_code."""
    def __init__(self, rows, company):
        self.rows, self.company = rows, company

    def sudo(self):
        return self

    def with_company(self, company):
        return SequenceModel(self.rows, company)

    def next_by_code(self, code):
        matches = [r for r in self.rows if r['code'] == code and r['company'] in (self.company, False)]
        matches.sort(key=lambda r: r['company'] is False)
        return matches[0]['reference'] if matches else False


def row(company, reference):
    return dict(company=company, reference=reference, code='hopland.birthday.booking')


class ReferenceFixChecks(unittest.TestCase):
    def lookup(self, rows, ambient=1, register=2):
        return reference_method()(SimpleNamespace(env={'ir.sequence': SequenceModel(rows, ambient)}),
                                  SimpleNamespace(company_id=register))

    def test_register_company_overrides_ambient_company(self):
        rows = [row(1, 'WRONG/001'), row(2, 'REGISTER/001'), row(False, 'SHARED/001')]
        self.assertEqual(self.lookup(rows), 'REGISTER/001')

    def test_shared_sequence_works_for_different_registers(self):
        for company in (1, 2, 3):
            self.assertEqual(self.lookup([row(False, 'BDAY/2026/00025')], register=company), 'BDAY/2026/00025')

    def test_foreign_company_sequence_does_not_leak(self):
        with self.assertRaisesRegex(ConfigurationError, 'No birthday booking sequence'):
            self.lookup([row(1, 'WRONG/001')])

    def test_migration_preserves_sequence_counter_and_identity(self):
        sequence = SimpleNamespace(_name='ir.sequence', code='hopland.birthday.booking', company_id=1,
                                   id=17, number_next_actual=84, prefix='BDAY/%(year)s/', padding=5)
        def write(vals):
            self.assertEqual(vals, {'company_id': False})
            sequence.__dict__.update(vals)
        sequence.write = Mock(side_effect=write)
        env = SimpleNamespace(ref=lambda xmlid: sequence)
        migrate = migration_function(env)
        migrate(None, '20.0.1.0.0')
        migrate(None, '20.0.1.0.0')
        sequence.write.assert_called_once_with({'company_id': False})
        self.assertEqual((sequence.id, sequence.number_next_actual, sequence.prefix, sequence.padding),
                         (17, 84, 'BDAY/%(year)s/', 5))

    def test_migration_refuses_unexpected_sequence(self):
        seq = SimpleNamespace(_name='ir.sequence', code='different.code', company_id=1, write=Mock())
        with self.assertRaises(ValueError):
            migration_function(SimpleNamespace(ref=lambda xmlid: seq))(None, '20.0.1.0.0')
        seq.write.assert_not_called()

    def test_fresh_install_sequence_is_shared(self):
        root = ET.parse(MODULE / 'data/sequence.xml').getroot()
        field = root.find("./record[@id='booking_sequence']/field[@name='company_id']")
        self.assertIsNotNone(field)
        self.assertEqual(field.get('eval'), 'False')


if __name__ == '__main__':
    unittest.main(verbosity=2)
