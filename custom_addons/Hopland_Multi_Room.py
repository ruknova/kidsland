"""Apply the optional additional rooms update to the Hopland birthday module."""
import argparse
import ast
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("module", type=Path)
args = parser.parse_args()
root = args.module.resolve()
updates = {}


def edit(rel, before, after, count=1):
    file = root / rel
    current = updates.get(file)
    if current is None:
        current = file.read_text(encoding="utf-8")
    if current.count(before) != count:
        raise SystemExit(f"Version mismatch or update already applied in {file}. No files changed.")
    updates[file] = current.replace(before, after)


booking = "models/booking.py"
wizard = "models/sales_wizard.py"
field = "    additional_room_ids = fields.Many2many('hopland.birthday.room', string='Additional rooms', check_company=True"
for rel, ending in [(booking, ", readonly=True, copy=False)"), (wizard, ")")]:
    marker = "    room_id = fields.Many2one("
    edit(rel, marker, field + ending + "\n" + marker)

edit(wizard, "        self.room_id = False", """        self.room_id = False
        self.additional_room_ids = False

    @api.onchange('room_id')
    def _onchange_primary_room(self):
        self.additional_room_ids -= self.room_id""")
edit(wizard, "'room_id': self.room_id.id,", "'room_id': self.room_id.id, 'additional_room_ids': self.additional_room_ids.ids,")
edit(booking, "        # Update the room guard", """        selected = payload.get('additional_room_ids', [])
        if not isinstance(selected, list) or any(type(value) is not int or value <= 0 for value in selected):
            raise UserError(_('Select valid additional rooms.'))
        room_ids = sorted(set(selected) | {room.id})
        rooms = self.env['hopland.birthday.room'].search([
            ('id', 'in', room_ids), ('active', '=', True), ('company_id', '=', config.company_id.id)], order='id')
        if rooms.ids != room_ids:
            raise UserError(_('Select active rooms from the reservation branch.'))
        # Update the room guard""")
edit(booking, """        self.env.cr.execute('UPDATE hopland_birthday_room SET reservation_lock_version = COALESCE(reservation_lock_version, 0) + 1 WHERE id = %s', [room.id])
        room.invalidate_recordset(['reservation_lock_version'])""", """        for selected_room in rooms:
            self.env.cr.execute('UPDATE hopland_birthday_room SET reservation_lock_version = COALESCE(reservation_lock_version, 0) + 1 WHERE id = %s', [selected_room.id])
        rooms.invalidate_recordset(['reservation_lock_version'])""")
edit(booking, "[('room_id', '=', room.id), ('state', '!=', 'cancelled')", "['|', ('room_id', 'in', room_ids), ('additional_room_ids', 'in', room_ids), ('state', '!=', 'cancelled')")
edit(booking, "This room already has a reservation at that time. Choose another time or room.", "A selected room already has a reservation at that time. Choose another time or room.")
# Preserve the original primary-room capacity rule for a group moving together.
edit(booking, "if children > room.capacity:", "if children > min(rooms.mapped('capacity')):")
edit(booking, "'This room holds at most %s children.', room.capacity", "'For a group visiting each selected room, the smallest room holds %s children.', min(rooms.mapped('capacity'))")
edit(booking, "{room.name}\\n", """{", ".join(rooms.mapped("name"))}\\n""")
edit(booking, "'room_id': room.id, 'partner_id':", "'room_id': room.id, 'additional_room_ids': [Command.set((rooms - room).ids)], 'partner_id':")
edit(booking, "'room': self.room_id.name,", """'room': ', '.join((self.room_id | self.additional_room_ids).mapped('name')),""")
edit("models/departments.py", "    room_id = fields.Many2one(related='booking_id.room_id')", """    room_id = fields.Many2one(related='booking_id.room_id')
    additional_room_ids = fields.Many2many(related='booking_id.additional_room_ids')""")
department = "views/department_views.xml"
line = """<field name="room_id" domain="[('company_id', '=', company_id)]" options="{'no_create': True}"/>"""
edit(department, line, line + """
                        <field name="additional_room_ids" widget="many2many_tags" domain="[('company_id', '=', company_id), ('id', '!=', room_id)]" options="{'no_create': True}"/>""")
for rel, count in [(department, 1), ("views/birthday_views.xml", 2)]:
    edit(rel, '<field name="room_id"/>', '<field name="room_id"/><field name="additional_room_ids" widget="many2many_tags"/>', count)
edit("views/birthday_views.xml", '<field name="room_id" filters="1"/>', '<field name="room_id" filters="1"/><field name="additional_room_ids"/>')
js = "static/src/birthday_dialog.js"
edit(js, 'roomId: 0,', 'roomId: 0, additionalRoomIds: [],')
edit(js, 'room_id: Number(this.state.roomId),', 'room_id: Number(this.state.roomId), additional_room_ids: this.state.additionalRoomIds,')
edit(js, '    input(field, event, price = false) {', """    toggleRoom(roomId, checked) {
        this.state.additionalRoomIds = this.state.additionalRoomIds.filter(id => id !== roomId);
        if (checked) this.state.additionalRoomIds.push(roomId);
    }
    input(field, event, price = false) {
        if (field === 'roomId') this.toggleRoom(Number(event.target.value), false);""")
xml = "static/src/birthday_dialog.xml"
anchor = '<label class="hb-wide">Party room'
source = (root / xml).read_text(encoding="utf-8")
line = next(line for line in source.splitlines() if anchor in line)
edit(xml, line, line + """
                                    <div class="hb-wide" t-if="this.state.catalog.rooms.length > 1">
                                        <span>Additional rooms (optional)</span>
                                        <t t-foreach="this.state.catalog.rooms" t-as="room" t-key="room.id">
                                            <label t-if="room.id !== Number(this.state.roomId)">
                                                <input type="checkbox" t-att-checked="this.state.additionalRoomIds.includes(room.id)" t-on-change="(e) => this.toggleRoom(room.id, e.target.checked)"/>
                                                <t t-out="room.name"/>
                                            </label>
                                        </t>
                                    </div>""".replace("Number(this.state.roomId)", "(+this.state.roomId)"))

for file, content in updates.items():
    if file.suffix == ".py":
        ast.parse(content, filename=str(file))
    elif file.suffix == ".xml":
        ElementTree.fromstring(content)
backup = root.parent.parent / "hopland_backups" / datetime.now().strftime("multi_room_%Y%m%d_%H%M%S_%f")
for file in updates:
    target = backup / file.relative_to(root)
    target.parent.mkdir(exist_ok=True, parents=True)
    shutil.copy2(file, target)
written = []
try:
    for file, content in updates.items():
        with tempfile.NamedTemporaryFile(dir=file.parent, delete=False) as staged:
            tmp = Path(staged.name)
            crlf = b"\r\n" in file.read_bytes()
            staged.write((content.replace("\n", "\r\n") if crlf else content).encode("utf-8"))
        try:
            shutil.copymode(file, tmp)
            os.replace(tmp, file)
            written.append(file)
        finally:
            tmp.unlink(missing_ok=True)
except BaseException:
    for file in written:
        shutil.copy2(backup / file.relative_to(root), file)
    raise
print(f"Updated {len(updates)} files. Original files saved under {backup}")
