// Native methods from runtime image f99ffac95cb3, Odoo LGPL-3.
class PosStore {
    setNextOrderRefs(order) {
        const deviceIdentifier = this.device.identifier;
        const number = `${this.device.useNext()}`.padStart(6, "0");
        const configId = this.config.id;
        const year2Digits = DateTime.now().year.toString().slice(-2);
        const posReference = `${year2Digits}${deviceIdentifier}-${configId}-${number}`;

        order.pos_reference = posReference;
        order.tracking_number = deviceIdentifier + `${parseInt(number) % 1000}`.padStart(3, "0");
    }
postSyncAllOrders(orders) {}
}
