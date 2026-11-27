import { Component, onWillStart, onWillDestroy, proxy, useProps, t } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { usePos } from '@point_of_sale/app/hooks/pos_hook';
import { uuidv4 } from '@point_of_sale/utils';

const { DateTime } = luxon;
export const errorText = (error) => error?.data?.message || error?.message || 'Unable to reach Odoo. Check the connection and try again.';

export class BirthdayDialog extends Component {
    static template = 'hopland_birthday_pos.BirthdayDialog';
    static components = { Dialog };
    props = useProps({ close: t.function(), templateId: t.number().optional(0), initialTab: t.string().optional('new') });

    setup() {
        this.pos = usePos();
        this.dead = false;
        this.priceSequence = 0;
        this.customerSequence = 0;
        const partner = this.pos.getOrder()?.partner_id;
        this.state = proxy({
            loading: true, busy: false, pricing: false, tab: 'new', error: '', priceError: '',
            catalog: { packages: [], rooms: [], timezone: 'Asia/Riyadh', branch: '' },
            packageId: 0, roomId: 0, additionalRoomIds: [], partnerId: partner?.id || 0,
            parent: partner?.name || '', phone: partner?.phone || '', email: partner?.email || '',
            child: '', age: 0, children: 10, adults: 0, start: '', stop: '', notes: '',
            discount: 0, services: {}, extras: {}, customers: [], quote: null, optionPrices: {},
            payMode: 'deposit', customDeposit: '', bookings: [], query: '',
            saved: null, requestUuid: uuidv4(),
        });
        onWillStart(async () => {
            await this.load();
            if (this.props.initialTab === 'bookings') await this.showBookings();
            this.bookingRefreshTimer = setInterval(async () => {
                if (!this.dead && this.state.tab === 'bookings' && !this.state.busy) {
                    try {
                        const bookings = await this.rpc('list_bookings', this.state.query);
                        if (!this.dead && this.state.tab === 'bookings' && !this.state.busy) this.state.bookings = bookings;
                    } catch { /* Next poll or manual search retries. */ }
                }
            }, 15000);
        });
        onWillDestroy(() => {
            this.dead = true;
            clearTimeout(this.priceTimer);
            clearTimeout(this.customerTimer);
            clearInterval(this.bookingRefreshTimer);
        });
    }

    async rpc(method, ...args) {
        return this.pos.data.call('hopland.birthday.booking', method, [this.pos.config.id, ...args]);
    }
    get selectedPackage() {
        return this.state.catalog.packages.find((p) => p.id === Number(this.state.packageId));
    }
    get payable() {
        if (!this.state.quote) return 0;
        if (this.state.payMode === 'full') return this.state.quote.total;
        if (this.state.payMode === 'custom') return Number(this.state.customDeposit) || 0;
        return this.state.quote.minimum_deposit;
    }
    money(value) { return this.pos.formatCurrency(Number(value) || 0); }
    image(templateId) { return `/web/image/product.template/${templateId}/image_128`; }
    dateLabel(utc, zone) {
        return DateTime.fromSQL(utc, { zone: 'utc' }).setZone(zone).toFormat('dd MMM yyyy · HH:mm');
    }
    async load() {
        try {
            this.state.catalog = await this.rpc('catalog');
            const p = this.state.catalog.packages.find((p) => p.template_id === this.props.templateId) || this.state.catalog.packages[0];
            this.state.roomId = this.state.catalog.rooms[0]?.id || 0;
            this.state.start = DateTime.now().setZone(this.state.catalog.timezone).plus({ days: 1 }).set({ hour: 17, minute: 0, second: 0 }).toFormat("yyyy-MM-dd'T'HH:mm");
            if (p) await this.choosePackage(p.id);
            else this.state.error = 'No birthday package is configured for this branch. Open Point of Sale → Birthdays → Packages in the backend.';
        } catch (error) { this.state.error = errorText(error); }
        finally { this.state.loading = false; }
    }
    async choosePackage(id) {
        this.state.packageId = Number(id);
        const p = this.selectedPackage;
        this.state.children = p.min_children;
        this.state.discount = 0;
        this.state.services = Object.fromEntries(p.services.map((s) => [s.id, true]));
        this.state.extras = {};
        this.updateStop();
        this.state.optionPrices = {};
        try {
            const all = await this.rpc('preview', { ...this.payload(), extra_ids: p.extras.map((e) => e.id), discount: 0 });
            if (this.selectedPackage?.id === p.id) {
                this.state.optionPrices = Object.fromEntries(all.lines.map((l) => [l.product_id, l.total / l.qty]));
            }
        } catch (error) { this.state.priceError = errorText(error); }
        await this.refreshPrice();
    }
    updateStop() {
        const start = DateTime.fromISO(this.state.start, { zone: this.state.catalog.timezone });
        this.state.stop = start.isValid ? start.plus({ hours: this.selectedPackage?.duration || 2 }).toFormat("yyyy-MM-dd'T'HH:mm") : '';
    }
    toggleRoom(roomId, checked) {
        this.state.additionalRoomIds = this.state.additionalRoomIds.filter(id => id !== roomId);
        if (checked) this.state.additionalRoomIds.push(roomId);
    }
    input(field, event, price = false) {
        if (field === 'roomId') this.toggleRoom(Number(event.target.value), false);
        this.state[field] = event.target.value;
        if (field === 'start') this.updateStop();
        if (field === 'parent' && !this.state.partnerId) this.searchCustomers();
        if (price) this.queuePrice();
    }
    changeCustomer() {
        this.state.partnerId = 0;
        this.state.parent = '';
        this.state.phone = '';
        this.state.email = '';
        this.state.customers = [];
        this.queuePrice();
    }
    searchCustomers() {
        clearTimeout(this.customerTimer);
        const sequence = ++this.customerSequence;
        this.customerTimer = setTimeout(async () => {
            try {
                const matches = await this.rpc('customers', this.state.parent);
                if (!this.dead && sequence === this.customerSequence) this.state.customers = matches;
            } catch (error) { if (!this.dead) this.state.error = errorText(error); }
        }, 250);
    }
    selectCustomer(customer) {
        this.customerSequence++;
        this.state.partnerId = customer.id;
        this.state.parent = customer.name;
        this.state.phone = customer.phone;
        this.state.email = customer.email;
        this.state.customers = [];
        this.queuePrice();
    }
    toggleExtra(id, event) {
        this.state.extras[id] = event.target.checked;
        this.queuePrice();
    }
    toggleService(id, event) { this.state.services[id] = event.target.checked; }
    queuePrice() {
        clearTimeout(this.priceTimer);
        this.state.pricing = true;
        this.priceSequence++;
        this.priceTimer = setTimeout(() => this.refreshPrice(), 250);
    }
    payload() {
        return {
            request_uuid: this.state.requestUuid, package_id: Number(this.state.packageId), room_id: Number(this.state.roomId), additional_room_ids: this.state.additionalRoomIds,
            partner_id: this.state.partnerId || false, parent_name: this.state.parent,
            phone: this.state.phone, email: this.state.email, child_name: this.state.child,
            age: Number(this.state.age), children: Number(this.state.children), adults: Number(this.state.adults),
            start: this.state.start, stop: this.state.stop, notes: this.state.notes, discount: Number(this.state.discount),
            service_ids: Object.entries(this.state.services).filter(([, yes]) => yes).map(([id]) => Number(id)),
            extra_ids: Object.entries(this.state.extras).filter(([, yes]) => yes).map(([id]) => Number(id)),
            expected_total: this.state.quote?.total,
        };
    }
    async refreshPrice() {
        clearTimeout(this.priceTimer);
        const sequence = ++this.priceSequence;
        this.state.pricing = true;
        this.state.priceError = '';
        try {
            const quote = await this.rpc('preview', this.payload());
            if (!this.dead && sequence === this.priceSequence) this.state.quote = quote;
        } catch (error) {
            if (!this.dead && sequence === this.priceSequence) {
                this.state.quote = null;
                this.state.priceError = errorText(error);
            }
        } finally {
            if (!this.dead && sequence === this.priceSequence) this.state.pricing = false;
        }
    }
    async showBookings() {
        this.state.tab = 'bookings';
        this.state.busy = true;
        this.state.error = '';
        try { this.state.bookings = await this.rpc('list_bookings', this.state.query); }
        catch (error) { this.state.error = errorText(error); }
        finally { this.state.busy = false; }
    }
    async submit(pay = true) {
        if (this.state.busy || this.state.pricing || !this.state.quote) return;
        this.state.error = '';
        if (!this.state.parent.trim() || !this.state.child.trim() || this.state.phone.trim().length < 7 || !this.state.start || !this.state.roomId) {
            this.state.error = 'Enter the parent, phone, child, party time and room.';
            return;
        }
        if (pay && (!Number.isFinite(this.payable) || this.payable < this.state.quote.minimum_deposit || this.payable > this.state.quote.total)) {
            this.state.error = `Payment must be between ${this.money(this.state.quote.minimum_deposit)} and ${this.money(this.state.quote.total)}.`;
            return;
        }
        this.state.busy = true;
        try {
            const booking = this.state.saved || await this.rpc('reserve', this.payload());
            this.state.saved = booking;
            if (pay) {
                const mode = this.payable >= this.state.quote.total ? 'full' : 'deposit';
                await this.pos.hoplandBeginCheckout(booking, mode, this.payable);
                this.props.close();
            } else {
                await this.showBookings();
            }
        } catch (error) {
            this.state.error = errorText(error) + (this.state.saved ? ' Your tentative booking is saved. Use Bookings to resume it.' : '');
        } finally { this.state.busy = false; }
    }
    async collect(booking, mode) {
        if (this.state.busy) return;
        this.state.busy = true;
        this.state.error = '';
        try {
            const amount = mode === 'full' ? booking.balance : Math.max(booking.minimum_deposit - booking.paid, 0);
            await this.pos.hoplandBeginCheckout(booking, mode, amount);
            this.props.close();
        } catch (error) { this.state.error = errorText(error); }
        finally { this.state.busy = false; }
    }
    async cancel(booking) {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            await this.rpc('cancel_tentative', booking.id);
            if (this.state.saved?.id === booking.id) this.resetForm();
            await this.showBookings();
        } catch (error) { this.state.error = errorText(error); }
        finally { this.state.busy = false; }
    }
    resetForm() {
        this.state.saved = null;
        this.state.requestUuid = uuidv4();
        this.state.child = '';
        this.state.notes = '';
    }
    newBooking() {
        if (this.state.saved) this.resetForm();
        this.state.tab = 'new';
        this.state.error = '';
    }
}
