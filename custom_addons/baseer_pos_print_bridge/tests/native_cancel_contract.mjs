// Exact relevant Odoo methods from QA asset 39917d0 (2026-11-10).
// Bundle SHA256: 6443d5f66a8c504aee0513c057303950eeda964dc2d064e6723ee91fdee3157d.
// Odoo LGPL-3. Keep the finalized-order assertion real in the regression fixture.
export const nativeOrderCancellation = {
    get finalized() { return this.state !== "draft"; },
    assertEditable() {
        if (this.finalized) throw new Error("Finalized Order cannot be modified");
        return true;
    },
    removeOrderline(line) {
        const linesToRemove = line.getAllLinesInCombo();
        for (const lineToRemove of linesToRemove) {
            if (lineToRemove.refunded_orderline_id?.uuid in this.uiState.lineToRefund) {
                delete this.uiState.lineToRefund[lineToRemove.refunded_orderline_id.uuid];
            }
            if (this.assertEditable()) lineToRemove.delete();
        }
        if (!this.lines.length) this.general_customer_note = "";
        this.selectOrderline(this.getLastOrderline());
        return true;
    },
};

export const nativeWholeOrderDeletion = {
    async onDeleteOrder(order) {
        const canDelete = await this.beforeDeleteOrder(order);
        if (!canDelete) return false;
        const refundedOrderLines = order.lines.filter((line) => line.refunded_orderline_id?.order_id)
            .map((line) => ({ order: line.refunded_orderline_id.order_id, uuid: line.refunded_orderline_id.uuid }));
        const orderIsDeleted = await this.deleteOrders([order]);
        if (!orderIsDeleted) return false;
        order.uiState.displayed = false;
        for (const refundedLine of refundedOrderLines) {
            delete refundedLine.order?.uiState?.lineToRefund[refundedLine.uuid];
        }
        await this.afterOrderDeletion();
        return true;
    },
    async afterOrderDeletion() {
        if (!this.config.module_pos_restaurant) {
            this.setOrder(this.getOpenOrders().at(-1) || this.addNewOrder());
        }
    },
};
