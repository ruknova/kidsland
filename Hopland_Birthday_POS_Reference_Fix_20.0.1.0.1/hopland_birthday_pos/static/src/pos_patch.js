import { patch } from '@web/core/utils/patch';
import { Navbar } from '@point_of_sale/app/components/navbar/navbar';
import { PosStore } from '@point_of_sale/app/services/pos_store';
import OrderPaymentValidation from '@point_of_sale/app/utils/order_payment_validation';
import { AlertDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { BirthdayDialog } from './birthday_dialog';

patch(Navbar.prototype, {
    openBirthdayReservations() { this.pos.hoplandOpenBirthday(); },
});

patch(PosStore.prototype, {
    hoplandOpenBirthday(templateId = 0) {
        this.dialog.add(BirthdayDialog, { templateId });
    },
    addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const template = typeof vals.product_tmpl_id === 'number'
            ? this.models['product.template'].get(vals.product_tmpl_id)
            : vals.product_tmpl_id || vals.product_id?.product_tmpl_id;
        if (configure && this.config.hopland_birthday_enabled && template?.hopland_birthday_product) {
            this.hoplandOpenBirthday(template.id);
            return Promise.resolve(undefined);
        }
        const promise = super.addLineToCurrentOrder(...arguments);
        // Odoo's native deposit helper starts async line additions without awaiting them.
        // Capture those promises so the payment screen never opens before all lines exist.
        this.hoplandLinePromises?.push(promise);
        return promise;
    },
    async hoplandBeginCheckout(booking, mode, amount) {
        if (this.data.network.offline) throw new Error('Reconnect to Odoo before reserving or collecting a birthday payment.');
        if (booking.checkout_uuid) {
            const existing = this.models['pos.order'].getBy('uuid', booking.checkout_uuid);
            if (!existing || existing.finalized) throw new Error('This reservation has a checkout on another device or an unsynced payment. Sync that device and reopen Bookings.');
            if (existing.lines.length) {
                this.selectedOrderUuid = existing.uuid;
                this.navigate('PaymentScreen', { orderUuid: existing.uuid });
                return;
            }
            this.selectedOrderUuid = existing.uuid;
            mode = booking.checkout_mode || mode;
            amount = booking.checkout_amount || amount;
        } else {
            // Preserve any unrelated cart. Never silently replace the customer's current sale.
            this.addNewOrder();
        }
        const order = this.getOrder();
        const data = await this.data.call('hopland.birthday.booking', 'checkout', [
            this.config.id, booking.id, order.uuid, mode, amount,
        ]);
        // Retain the lock reference even if loading SO data fails; retry resumes this same cart.
        booking.checkout_uuid = order.uuid;
        booking.checkout_amount = data.amount;
        booking.checkout_mode = data.mode;
        const sale = await this._getSaleOrder(data.sale_order_id);
        order.setPartner(sale.partner_id);
        if (sale.pricelist_id) order.setPricelist(sale.pricelist_id);
        order.update({ fiscal_position_id: sale.fiscal_position_id, hopland_booking_uuid: data.request_uuid });
        this.hoplandLinePromises = [];
        try {
            if (mode === 'full') {
                await this.settleSO(sale, sale.fiscal_position_id);
            } else {
                this.addDownPaymentProductOrderlineToOrder(sale, data.amount, false);
            }
            await Promise.all(this.hoplandLinePromises);
            if (Math.abs(order.amount_total - data.amount) > this.currency.rounding / 2) {
                throw new Error('The native POS total differs from the reservation payment. Do not pay; ask a manager to review the linked sales order.');
            }
            const afterPayment = Math.max(data.balance - data.amount, 0);
            const localStart = luxon.DateTime.fromSQL(data.start, { zone: 'utc' }).setZone(data.timezone).toFormat('dd MMM yyyy HH:mm');
            order.setGeneralCustomerNote(
                `${data.reference} | ${data.child} | ${data.children} children\n` +
                `${data.room} | ${localStart} (${data.timezone})\n` +
                `Booking total: ${this.formatCurrency(data.total)} | This payment: ${this.formatCurrency(data.amount)}\n` +
                `Balance after this payment: ${this.formatCurrency(afterPayment)}`
            );
            this.selectOrderLine(order, order.lines.at(-1));
            this.navigate('PaymentScreen', { orderUuid: order.uuid });
        } catch (error) {
            // Keep the saved reservation and checkout UUID for recovery, but don't retain half-built lines.
            for (const line of [...order.lines]) line.delete();
            throw error;
        } finally { this.hoplandLinePromises = null; }
    },
});

patch(OrderPaymentValidation.prototype, {
    async isOrderValid() {
        if (this.order.hopland_booking_uuid) {
            if (this.pos.data.network.offline) {
                this.pos.dialog.add(AlertDialog, { title: 'Connection required', body: 'Reconnect before collecting this birthday payment.' });
                return false;
            }
            if (this.order.payment_ids.some((p) => p.payment_method_id.type === 'pay_later')) {
                this.pos.dialog.add(AlertDialog, { title: 'Payment required', body: 'Use cash or a configured payment method. Customer Account does not secure a birthday reservation.' });
                return false;
            }
        }
        return super.isOrderValid(...arguments);
    },
});
