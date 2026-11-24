{
    'name': 'Hopland Birthday Reservations for POS',
    'version': '20.0.1.0.1',
    'summary': 'Birthday packages, service checklist, room calendar and POS deposits',
    'category': 'Sales/Point of Sale',
    'author': 'Hopland implementation project',
    'license': 'LGPL-3',
    'depends': ['pos_sale'],
    'data': ['security/ir.access.csv', 'data/sequence.xml', 'views/birthday_views.xml'],
    'assets': {'point_of_sale._assets_pos': [
        'hopland_birthday_pos/static/src/birthday_dialog.js',
        'hopland_birthday_pos/static/src/birthday_dialog.xml',
        'hopland_birthday_pos/static/src/birthday.scss',
        'hopland_birthday_pos/static/src/pos_patch.js',
    ]},
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
