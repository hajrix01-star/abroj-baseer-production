/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { RPCError } from "@web/core/network/rpc";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { SplitBillScreen } from "@pos_restaurant/app/screens/split_bill_screen/split_bill_screen";
import "./preparation_bridge";

const pendingField = "baseerBillSplitPending";
const pendingMessage = () => _t("Confirm the pending kitchen change before payment.");
const clone = (value) => JSON.parse(JSON.stringify(value));
function stopSplit(screen) {
    if (screen._baseerPaySplit) {
        const error = new Error(pendingMessage());
        error.baseerBillSplitStopped = true;
        throw error;
    }
    return false;
}

export function baseerSplitIsBlocked(pos, order) {
    return Boolean(!order || pos.data.network.offline || order.uiState[pendingField]
        || order.uiState.baseerPreparationAction || order.uiState.baseerPreparationOutcomeUnknown
        || order.uiState.baseerRestaurantMergePending || pos._baseerPreparationResolutions?.has(order.uuid)
        || pos._baseerKitchenSends?.has(order.uuid) || pos.syncingOrders.has(order.uuid)
        || pos.baseerHasPendingProtectedAction?.(order));
}

patch(SplitBillScreen.prototype, {
    async paySplittedOrder() {
        this._baseerPaySplit = true;
        try { return await super.paySplittedOrder(...arguments); }
        catch (error) {
            if (!error.baseerBillSplitStopped) throw error;
            return false;
        } finally { delete this._baseerPaySplit; }
    },
    async createSplittedOrder() {
        if (!this.pos.config.baseer_direct_print_enabled) return super.createSplittedOrder(...arguments);
        const pos = this.pos;
        const original = this.currentOrder;
        if (baseerSplitIsBlocked(pos, original)) {
            pos.notification.add(pendingMessage(), { type: "warning" });
            return stopSplit(this);
        }
        if (this.getNumberOfProducts() >= this.totOrderQty) {
            pos.notification.add(_t("To pay the whole order, use Payment without splitting it."), { type: "warning" });
            return stopSplit(this);
        }
        let marker;
        pos.env.services.ui.block();
        pos._baseerBillSplitRunning = true;
        try {
            // Finish native synchronization before native splitting changes any line.
            await pos.syncAllOrders({ orders: [original], force: true, throw: true });
            if (baseerSplitIsBlocked(pos, original) || !original.isSynced) throw new Error(pendingMessage());
            const baseline = await pos.data.call("pos.order", "baseer_prepare_bill_split", [[original.id]], {}, false);
            if (baseerSplitIsBlocked(pos, original)) throw new Error(pendingMessage());
            marker = { source_uuid: original.uuid, baseline, lines: [] };
            original.uiState[pendingField] = marker;
            original._baseerSplitMutation = true;
            pos._baseerBillSplitCapture = marker;
            // Odoo still creates the child, moves the lines, and handles discounts/combos.
            return await super.createSplittedOrder(...arguments);
        } catch (error) {
            if (marker && (!marker.sent || marker.rejected)) await pos._baseerRejectBillSplit(marker);
            pos.notification.add(error?.data?.message || pendingMessage(), { type: "warning" });
            return stopSplit(this);
        } finally {
            delete original._baseerSplitMutation;
            const child = marker?.target_uuid && pos.models["pos.order"].getBy("uuid", marker.target_uuid);
            if (child) delete child._baseerSplitMutation;
            delete pos._baseerBillSplitCapture;
            pos._baseerBillSplitRunning = false;
            pos.env.services.ui.unblock();
            await pos.data.synchronizeLocalDataInIndexedDB();
        }
    },
});

patch(PosStore.prototype, {
    handlePreparationHistory(srcPrep, destPrep, srcLine, destLine, quantity) {
        const result = super.handlePreparationHistory(...arguments);
        const marker = this._baseerBillSplitCapture;
        if (marker && srcLine.order_id?.uuid === marker.source_uuid) {
            const child = destLine.order_id;
            marker.target_uuid = child.uuid;
            marker.lines.push({ source_uuid: srcLine.uuid, target_uuid: destLine.uuid, quantity });
            child.uiState[pendingField] = marker;
            child._baseerSplitMutation = true;
        }
        return result;
    },

    async syncAllOrders(options = {}) {
        const pending = this.getPendingOrder();
        const requested = options.orders || [...pending.orderToCreate, ...pending.orderToUpdate];
        const markers = new Map(requested.filter((order) => order.uiState[pendingField])
            .map((order) => [order.uiState[pendingField].source_uuid, order.uiState[pendingField]]));
        const synced = [];
        for (const marker of markers.values()) {
            // Autosync must not serialize the half-built native split.
            if (!marker.payloads && !(options.orders?.length === 2 && marker.target_uuid
                && options.orders.some((order) => order.uuid === marker.target_uuid))) continue;
            synced.push(...await this._baseerSyncBillSplit(marker, options));
        }
        const ordinary = requested.filter((order) => !markers.has(order.uuid)
            && ![...markers.values()].some((marker) => marker.target_uuid === order.uuid));
        if (ordinary.length) synced.push(...(await super.syncAllOrders({ ...options, orders: ordinary }) || []));
        return synced;
    },

    async _baseerSyncBillSplit(marker, options) {
        this._baseerBillSplitSyncs ||= new Map();
        if (this._baseerBillSplitSyncs.has(marker.source_uuid)) return this._baseerBillSplitSyncs.get(marker.source_uuid);
        const work = this._baseerFlushBillSplit(marker, options);
        this._baseerBillSplitSyncs.set(marker.source_uuid, work);
        try { return await work; }
        finally { this._baseerBillSplitSyncs.delete(marker.source_uuid); }
    },

    async _baseerFlushBillSplit(marker, options) {
        if (marker.rejected) { await this._baseerRejectBillSplit(marker); return []; }
        const byUuid = (uuid) => this.models["pos.order"].getBy("uuid", uuid);
        const source = byUuid(marker.source_uuid);
        const child = byUuid(marker.target_uuid);
        if (this.data.network.offline || !source || !child
            || [source, child].some((order) => order.uiState.baseerPreparationOutcomeUnknown
                || this._baseerPreparationResolutions?.has(order.uuid))) throw new Error(pendingMessage());
        if (!marker.payloads) {
            await this.preSyncAllOrders([source, child]);
            marker.payloads = clone([source, child].map((order) => order.serializeForORM({ keepCommands: true })));
            marker.context = this.getSyncAllOrdersContext([source, child], { ...options, context: {
                ...options.context, baseer_native_split: {
                    source_uuid: marker.source_uuid, target_uuid: marker.target_uuid,
                    baseline: marker.baseline, lines: marker.lines,
                },
            } });
            await this.data.synchronizeLocalDataInIndexedDB();
        }
        marker.sent = true;
        let data;
        try {
            // Native POS normally syncs one order per RPC. A split pair must commit together.
            data = await this.data.call("pos.order", "sync_from_ui", [clone(marker.payloads)], { context: marker.context }, false);
        } catch (error) {
            if (error instanceof RPCError) marker.rejected = true;
            throw error;
        }
        for (const order of [source, child]) order.serializeForORM();
        data = await this.data.missingRecursive(data);
        const loaded = this.models.loadConnectedData(data);
        const pair = [byUuid(marker.source_uuid), byUuid(marker.target_uuid)];
        if (pair.some((order) => !order || !order.isSynced)) throw new Error(pendingMessage());
        for (const order of pair) order.uiState[pendingField] = marker;
        const current = () => !this.data.network.offline && pair.every((order) =>
            byUuid(order.uuid) === order && order.uiState[pendingField]?.baseline === marker.baseline);
        await this._baseerPersistPreparationSnapshot(data, pair[0], [], [pendingField], current);
        for (const order of pair) {
            delete order.uiState[pendingField];
            this.removePendingOrder(order);
        }
        await this.postSyncAllOrders(loaded["pos.order"]);
        if (!this._baseerBillSplitRunning) {
            this.setOrder(pair[1]);
            this.navigate("ProductScreen", { orderUuid: pair[1].uuid });
        }
        return loaded["pos.order"];
    },

    async _baseerRejectBillSplit(marker) {
        const source = this.models["pos.order"].getBy("uuid", marker.source_uuid);
        const child = this.models["pos.order"].getBy("uuid", marker.target_uuid);
        if (!source) return false;
        const stale = source.uiState.baseerPreparationStaleRecords ||= [];
        if (child) {
            const lines = [...child.lines];
            for (const [model, inverse, owners] of [
                ["pos.pack.operation.lot", "pos_order_line_id", lines],
                ["product.attribute.custom.value", "pos_order_line_id", lines],
                ["pos.order.line", "order_id", [child]],
                ["pos.payment", "pos_order_id", [child]],
                ["restaurant.order.course", "order_id", [child]],
            ]) {
                const ids = new Set(owners.map((record) => record.id));
                for (const record of this.models[model]?.filter((row) => ids.has(row[inverse]?.id)) || []) {
                    stale.push([model, record[this.data.opts.databaseTable[model]?.key || "id"]]);
                    record.delete({ silent: true });
                }
            }
            stale.push(["pos.order", child[this.data.opts.databaseTable["pos.order"]?.key || "id"]]);
            this.removePendingOrder(child);
            child.delete({ silent: true });
        }
        try {
            const current = () => source.uiState[pendingField]?.baseline === marker.baseline;
            const restored = await this._baseerRestoreCanonicalOrder(source, {},
                [pendingField, "baseerPreparationStaleRecords"], current);
            if (!restored) return false;
            delete source.uiState[pendingField];
            delete source.uiState.baseerPreparationStaleRecords;
            delete source.uiState.splittedOrderUuid;
            this.removePendingOrder(source);
            this.setOrder(source);
            this.navigate("ProductScreen", { orderUuid: source.uuid });
            return true;
        } catch { return false; }
    },
});
