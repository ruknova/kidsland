"""Run with: python tests/test_validation_standalone.py (no Odoo/database needed)."""
import base64
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pc_validation', Path(__file__).parents[1] / 'models' / 'validation.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class ValidationTests(unittest.TestCase):
    def test_pdf(self):
        raw = b'%PDF-1.4\nexample\n%%EOF'
        data, mime, digest = v.receipt_file(base64.b64encode(raw), 'receipt.pdf')
        self.assertEqual(data, raw)
        self.assertEqual(mime, 'application/pdf')
        self.assertEqual(len(digest), 64)

    def test_png(self):
        _, mime, _ = v.receipt_file(base64.b64encode(b'\x89PNG\r\n\x1a\nexample'), 'r.png')
        self.assertEqual(mime, 'image/png')

    def test_jpeg(self):
        _, mime, _ = v.receipt_file(base64.b64encode(b'\xff\xd8\xff' + b'example bytes'), 'r.JPG')
        self.assertEqual(mime, 'image/jpeg')

    def test_missing_upload(self):
        with self.assertRaises(ValueError):
            v.receipt_file(False, 'r.pdf')

    def test_missing_name(self):
        with self.assertRaises(ValueError):
            v.receipt_file(base64.b64encode(b'%PDF-1.4example'), '')

    def test_invalid_encoding(self):
        with self.assertRaises(ValueError):
            v.receipt_file(b'%%%bad', 'r.pdf')

    def test_html_disguised_as_pdf(self):
        with self.assertRaises(ValueError):
            v.receipt_file(base64.b64encode(b'<html>not a receipt</html>'), 'r.pdf')

    def test_extension_mismatch(self):
        with self.assertRaises(ValueError):
            v.receipt_file(base64.b64encode(b'%PDF-1.4example'), 'r.exe')

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            v.receipt_file(b'A' * (v.MAX_RECEIPT_BYTES * 4 // 3 + 20), 'r.pdf')

    def test_reference_case_and_spaces(self):
        self.assertEqual(v.reference_key(1, 2, ' PC-001 '), v.reference_key(1, 2, 'pc-001'))

    def test_reference_company_and_vendor_scope(self):
        self.assertNotEqual(v.reference_key(1, 2, 'PC-001'), v.reference_key(2, 2, 'PC-001'))
        self.assertNotEqual(v.reference_key(1, 2, 'PC-001'), v.reference_key(1, 3, 'PC-001'))

    def test_blank_reference(self):
        with self.assertRaises(ValueError):
            v.reference_key(1, 2, '   ')

    def test_nonfinite_or_nonpositive_amounts(self):
        for value in [float('nan'), float('inf'), float('-inf'), -1, 0]:
            with self.subTest(value=value):
                self.assertFalse(v.positive_amount(value))
        self.assertTrue(v.positive_amount(172.5))

    def test_receipt_identity_ignores_filename(self):
        receipt = base64.b64encode(b'%PDF-1.4example')
        self.assertEqual(v.receipt_file(receipt, 'first.pdf')[2], v.receipt_file(receipt, 'renamed.pdf')[2])


if __name__ == '__main__':
    unittest.main(verbosity=2)
