module = env['ir.module.module'].search([('name', '=', 'hopland_birthday_pos')], limit=1)
assert module.state == 'installed'
assert module.latest_version == '20.0.1.2.0', module.latest_version
Review = env['hopland.party.receipt.review']
menu = env.ref('hopland_birthday_pos.party_receipt_review_menu')
booking_menu = env.ref('hopland_birthday_pos.party_accounting_menu')
assert menu.parent_id and menu.parent_id == booking_menu.parent_id, 'Accounting menus have different parents'
assert env.ref('hopland_birthday_pos.activity_party_receipt_review').res_model == Review._name
print('Accounting menu parent:', menu.parent_id.complete_name)
reviews = Review.search([])
print('Party receipt reviews:', len(reviews))
activity_domain = [('res_model', '=', Review._name)]
before = (len(reviews), env['mail.activity'].search_count(activity_domain))
reviews.picking_id._create_hopland_receipt_reviews()
assert before == (Review.search_count([]), env['mail.activity'].search_count(activity_domain)), 'Repeated handoff duplicated reviews/tasks'
for review in reviews:
    assert review.company_id == review.booking_id.company_id == review.purchase_id.company_id
    assert review.picking_id.state == 'done'
    print('Review:', review.receipt_reference, '/', review.purchase_reference,
          '/', review.booking_id.name, '/ accountants notified:', len(review.notified_user_ids))
    if not review.notified_user_ids:
        print('NOTICE: No eligible accountant for this branch. The review remains in the list.')
group = env.ref('account.group_account_user')
users = env['res.users'].search([('active', '=', True), ('share', '=', False),
                               ('all_group_ids', 'in', group.ids)])
for user in users:
    for company in user.company_ids:
        visible = Review.with_user(user).with_context(allowed_company_ids=[company.id]).search([])
        assert all(r.company_id == company for r in visible), 'Receipt review company boundary failed'
        visible.read(['name', 'booking_id', 'supplier_name', 'received_items', 'purchase_total', 'state'])
        if visible:
            visible.get_view(view_id=env.ref('hopland_birthday_pos.party_receipt_review_form').id, view_type='form')
            action = visible[:1].action_vendor_bills()
            env['account.move'].with_user(user).with_context(allowed_company_ids=[company.id]).search(action['domain'], limit=1)
print('HOPLAND_RECEIPT_HANDOFF_OK')
print('No bill, payment, order, reservation or receipt was created by verification.')
env.cr.rollback()
