{
    'name': 'Hopland Purchasing Petty Cash',
    'version': '20.0.1.0.0',
    'summary': 'Receipt-backed purchasing payments from assigned department cash funds',
    'category': 'Accounting/Accounting',
    'author': 'Hopland implementation project',
    'license': 'LGPL-3',
    'depends': ['hopland_birthday_pos', 'account', 'purchase_stock'],
    'data': ['security/ir.access.csv', 'data/data.xml', 'views/petty_cash_views.xml'],
    'application': False,
    'installable': True,
}
