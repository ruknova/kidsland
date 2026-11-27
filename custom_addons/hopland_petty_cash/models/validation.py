"""Pure validation used by the server workflow; no Odoo dependency."""
import base64
import binascii
import hashlib
import math
from pathlib import PurePath

MAX_RECEIPT_BYTES = 10 * 1024 * 1024


def receipt_file(encoded, filename):
    if not encoded or not filename:
        raise ValueError('Upload the vendor receipt before confirming payment.')
    if len(encoded) > (MAX_RECEIPT_BYTES * 4 // 3) + 8:
        raise ValueError('The receipt must be 10 MB or smaller.')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('The receipt upload is not valid base64 data.') from error
    suffix = PurePath(filename).suffix.lower()
    valid = ((suffix == '.pdf' and data.startswith(b'%PDF-')) or
             (suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or
             (suffix in ('.jpg', '.jpeg') and data.startswith(b'\xff\xd8\xff')))
    if not valid or len(data) < 12:
        raise ValueError('Upload a PDF, PNG or JPEG receipt with the matching extension.')
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError('The receipt must be 10 MB or smaller.')
    mime = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}[suffix]
    return data, mime, hashlib.sha256(data).hexdigest()


def positive_amount(value):
    return math.isfinite(value) and value > 0


def reference_key(company_id, vendor_id, reference):
    ref = (reference or '').strip().lower()
    if not ref:
        raise ValueError('Enter the vendor receipt/invoice reference.')
    return hashlib.sha256(f'{company_id}:{vendor_id}:{ref}'.encode()).hexdigest()
