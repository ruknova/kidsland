import { patch } from '@web/core/utils/patch';
import { PosStore } from '@point_of_sale/app/services/pos_store';
import { BirthdayDialog } from './birthday_dialog';

// Polling also works on Windows installations without a separate websocket worker.
// Only the current register's authorized Sales bookings are returned by the server.
patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        if (!this.config.hopland_birthday_enabled) return;
        this.hoplandSalesCursor = null;
        const poll = async () => {
            try {
                if (!this.data.network.offline) {
                    const result = await this.data.call('hopland.birthday.booking', 'sales_arrivals', [
                        this.config.id, this.hoplandSalesCursor,
                    ]);
                    this.hoplandSalesCursor = result.cursor;
                    if (result.bookings.length) {
                        this.notification.add(
                            `${result.bookings.length} Sales reservation(s): ${result.bookings.map(b => b.reference).join(', ')}`,
                            { title: 'New party reservations', type: 'info', sticky: true,
                              buttons: [{ name: 'Bookings & balances', primary: true,
                                  onClick: () => this.dialog.add(BirthdayDialog, { initialTab: 'bookings' }) }] }
                        );
                    }
                }
            } catch {
                // Keep the cursor unchanged and retry after temporary network/session errors.
            } finally {
                this.hoplandSalesTimer = setTimeout(poll, 15000);
            }
        };
        void poll();
    },
});
