/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { SERIALIZED_UI_STATE_PROP } from "@point_of_sale/app/models/related_models/utils";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import { ask, makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { buildBaseerPreparationAction } from "./line_actions";

const BASEER_CANCELLATION_REASONS = [
    ["customer_cancelled", _t("Customer cancelled")],
    ["wrong_order", _t("Wrong order")],
    ["duplicate_order", _t("Duplicate order")],
    ["unavailable_item", _t("Item unavailable")],
    ["staff_error", _t("Staff error")],
    ["other", _t("Other")],
];

/**
 * Native POS remains responsible for syncing and for its own preparation flow.
 * Once that sync completes, the server derives the printable delta from its
 * trusted order state. No printer address, category, text or route is supplied
 * by the browser.
 */
patch(PosStore.prototype, {
    async _baseerConfirmPaymentWithoutKitchen() {
        let order = this.getOrder();
        if (order?.uiState?.baseerPreparationOutcomeUnknown || this._baseerPreparationResolutions?.has(order?.uuid)) {
            if (!(await this.baseerResolvePreparationOutcome(order))) return false;
            order = this.models?.["pos.order"]?.getBy("uuid", order.uuid) || order;
        }
        if (order?.uiState?.baseerPreparationAction) {
            this.notification.add(_t("Confirm the pending kitchen change before payment."), { type: "warning" });
            return false;
        }
        const hasBaseerChanges = order
            ? buildBaseerPreparationAction(order, "send").lines.length > 0
            : false;
        if (!hasBaseerChanges || order.isRefund) {
            return true;
        }
        return await ask(this.dialog, {
            title: _t("Kitchen changes not sent"),
            body: _t(
                "This order has changes that were not sent to the kitchen. Continue to payment without sending them?"
            ),
            confirmLabel: _t("Continue payment without sending"),
            confirmClass: "btn-warning",
            cancelLabel: _t("Back"),
        });
    },

    async _askForPreparation() {
        if (!this.config.baseer_direct_print_enabled) {
            return await super._askForPreparation(...arguments);
        }
        // Baseer intentionally separates payment from kitchen dispatch. Only
        // the explicit Send/Update Kitchen actions may create an audited event.
        return false;
    },

    async pay() {
        if (this.config.baseer_direct_print_enabled && !(await this._baseerConfirmPaymentWithoutKitchen())) {
            return false;
        }
        return await super.pay(...arguments);
    },

    async validateOrderFast(paymentMethod) {
        if (this.config.baseer_direct_print_enabled && !(await this._baseerConfirmPaymentWithoutKitchen())) {
            return false;
        }
        return await super.validateOrderFast(paymentMethod);
    },

    async _baseerPreparationStatus(order, action) {
        if (!action?.action_uuid || !order?.uuid || this.data.network.offline) {
            return null;
        }
        return await this.data.silentCall(
            "baseer.print.preparation.event", "baseer_action_status",
            [action.action_uuid, order.uuid], {}, false
        );
    },

    async baseerResolvePreparationOutcome(order) {
        // Persistence clears flags before its asynchronous commit. Controls
        // entering in that window must still await the same durable result.
        if (this._baseerPreparationResolutions?.has(order?.uuid)) {
            return this._baseerPreparationResolutions.get(order.uuid);
        }
        if (!order?.uiState?.baseerPreparationOutcomeUnknown) {
            return true;
        }
        const action = order.uiState.baseerPreparationAction;
        if (!action?.action_uuid || !order.uuid || this.data.network?.offline) return false;
        this._baseerPreparationResolutions ||= new Map();
        const key = order.uuid;
        if (this._baseerPreparationResolutions.has(key)) {
            return this._baseerPreparationResolutions.get(key);
        }
        const resolution = this._baseerResolvePreparationAttempt(order, action);
        this._baseerPreparationResolutions.set(key, resolution);
        try {
            return await resolution;
        } finally {
            this._baseerPreparationResolutions.delete(key);
        }
    },

    async _baseerResolvePreparationAttempt(order, action) {
        const matches = (candidate) => candidate?.uiState?.baseerPreparationAction?.action_uuid === action.action_uuid;
        const fields = ["baseerPreparationAction", "baseerPreparationOutcomeUnknown", "baseerPreparationPreviousChange", "baseerPreparationStaleRecords"];
        const orderId = order.id;
        const orderUuid = order.uuid;
        const companyId = order.company_id?.id;
        const configId = order.config_id?.id;
        const isCurrent = () => matches(order) && !this.data.network.offline
            && order.id === orderId && order.uuid === orderUuid
            && order.company_id?.id === companyId && order.config_id?.id === configId
            && this.models["pos.order"].getBy("uuid", orderUuid) === order;
        try {
            if (!companyId || !configId || this.config.id !== configId
                || this.config.company_id?.id !== companyId || !isCurrent()) return false;
            let status = await this._baseerPreparationStatus(order, action);
            if (!isCurrent()) return false;
            if (!status?.accepted) {
                // An atomic server receipt retires an unaccepted attempt. A
                // delayed copy of the original payload cannot send it later.
                if (!order.isSynced || !Number.isInteger(order.id)) return false;
                status = await this.data.silentCall(
                    "pos.order", "baseer_resolve_preparation_action", [[order.id], action], {}, false
                );
            }
            if (!status?.accepted || !isCurrent()) return false;
            // This native point read returns the complete financial graph, even
            // when write_date is unchanged. Do not merge via callRelated/read or
            // autosync the uncertain intent while obtaining the snapshot.
            let snapshot = await this.data.call("pos.order", "read_pos_data_uuid", [order.uuid], {}, false);
            if (!isCurrent() || !this._baseerValidPreparationSnapshot(snapshot, order, status)) return false;
            snapshot = await this.data.missingRecursive(snapshot);
            if (!isCurrent() || !this._baseerValidPreparationSnapshot(snapshot, order, status)) return false;
            // missingRecursive intentionally tolerates some read failures.
            // An unresolved relation is not a complete recovery snapshot.
            for (const [model, records] of Object.entries(snapshot)) {
                for (const field of Object.values(this.data.relations[model] || {})) {
                    if (!field.relation || !this.models[field.relation]) continue;
                    for (const record of records) {
                        const ids = Array.isArray(record[field.name]) ? record[field.name] : [record[field.name]];
                        if (ids.some((id) => typeof id === "number" && id
                            && !snapshot[field.relation]?.some((related) => related.id === id)
                            && !this.models[field.relation].get(id))) return false;
                    }
                }
            }

            // Native loading retains unsynced children in x2many fields. Remove
            // this order's stale children first, including detached backrefs.
            // Deletion records ORM commands even when silent: consume those
            // locally BEFORE loading, so they cannot cancel canonical lines on
            // the next payment. No serialized payload is sent to the server.
            const localLines = this.models["pos.order.line"].filter((line) => line.order_id?.id === order.id);
            const localCourses = this.models["restaurant.order.course"]?.filter((course) => course.order_id?.id === order.id) || [];
            // Keep deletion tombstones with the uncertain intent until their
            // IndexedDB removal succeeds, including retries after a failed save.
            const staleKeys = order.uiState.baseerPreparationStaleRecords || [];
            order.uiState.baseerPreparationStaleRecords = staleKeys;
            for (const [model, inverse, owners] of [
                ["pos.pack.operation.lot", "pos_order_line_id", localLines],
                ["product.attribute.custom.value", "pos_order_line_id", localLines],
                ["pos.order.line", "order_id", [order]],
                ["pos.payment", "pos_order_id", [order]],
                ["restaurant.order.course", "order_id", [order]],
            ]) {
                const ownerIds = new Set(owners.map((owner) => owner.id));
                const serverIds = new Set((snapshot[model] || []).map((record) => record.id));
                const stale = this.models[model]?.filter((record) => ownerIds.has(record[inverse]?.id) && !serverIds.has(record.id)) || [];
                for (const record of stale) {
                    const key = this.data.opts.databaseTable[model]?.key || "id";
                    staleKeys.push([model, record[key]]);
                    record.delete({ silent: true });
                }
            }
            for (const line of localLines) line.serializeForORM();
            for (const course of localCourses) course.serializeForORM();
            order.serializeForORM();
            this.models.loadConnectedData(snapshot, []);
            if (!isCurrent()) return false;
            const canonical = snapshot["pos.order"][0];
            if (order.state !== canonical.state || order.company_id?.id !== companyId
                || order.config_id?.id !== configId
                || !this._baseerSamePreparationIds(order.lines, canonical.lines)
                || !this._baseerSamePreparationIds(order.payment_ids, canonical.payment_ids)
                || order.lines.some((line) => line.order_id !== order)
                || order.payment_ids.some((payment) => payment.pos_order_id !== order)) return false;
            if (canonical.course_ids && (!this._baseerSamePreparationIds(order.course_ids, canonical.course_ids)
                || order.course_ids.some((course) => course.order_id !== order))) return false;
            // Keep recovery flags in memory until the entire canonical graph,
            // stale deletions and unblocked order have committed atomically.
            await this._baseerPersistPreparationSnapshot(snapshot, order, staleKeys, fields, isCurrent);
            if (!isCurrent()) return false;
            for (const field of fields) delete order.uiState[field];
            this.removePendingOrder(order);
            this._baseerNotifyPreparationStatus(status);
            return true;
        } catch {
            return false;
        }
    },

    async _baseerPersistPreparationSnapshot(snapshot, order, staleKeys, fields, isCurrent) {
        return this.data.indexedDBMutex.exec(() => {
            if (!isCurrent()) throw new Error("Preparation recovery changed before persistence.");
            const rows = {};
            for (const [model, records] of Object.entries(snapshot)) {
                rows[model] = records.map((record) => this.models[model].get(record.id).serializeForIndexedDB());
            }
            const serializedOrder = rows["pos.order"][0];
            const state = JSON.parse(serializedOrder[SERIALIZED_UI_STATE_PROP]);
            for (const field of fields) delete state[field];
            serializedOrder[SERIALIZED_UI_STATE_PROP] = JSON.stringify(state);
            const stores = [...new Set([...Object.keys(rows).filter((model) => rows[model].length),
                ...staleKeys.map(([model]) => model)])];
            // Native IndexedDB.create resolves on request success and converts
            // request failures into result objects. Recovery must await the
            // transaction's actual commit and reject an abort/error instead.
            return new Promise((resolve, reject) => {
                const database = this.data.indexedDB;
                const transaction = database.getNewTransaction(stores);
                if (!transaction) {
                    reject(new Error("Preparation recovery storage is unavailable."));
                    return;
                }
                let settled = false;
                const timeout = setTimeout(() => abort(new Error("Preparation recovery storage timed out.")), 15000);
                const finish = (error) => {
                    if (settled) return;
                    settled = true;
                    clearTimeout(timeout);
                    database.activeTransactions.delete(transaction);
                    if (error) reject(error);
                    else resolve();
                };
                const abort = (error) => {
                    try {
                        transaction.abort();
                    } catch {
                        // A transaction may already have been aborted.
                    }
                    finish(error);
                };
                transaction.addEventListener("complete", () => finish(), { once: true });
                transaction.addEventListener("abort", () => finish(transaction.error || new Error("Preparation recovery storage was aborted.")), { once: true });
                transaction.addEventListener("error", () => abort(transaction.error || new Error("Preparation recovery storage failed.")), { once: true });
                const guardRequest = (request) => {
                    request.addEventListener("success", () => {
                        // Request callbacks still run inside the active native
                        // readwrite transaction. Abort before commit if a newer
                        // intent, replacement order or disconnect invalidated
                        // the clean UI-state snapshot while requests waited.
                        if (!isCurrent()) abort(new Error("Preparation recovery changed during persistence."));
                    }, { once: true });
                };
                try {
                    for (const [model, key] of staleKeys) guardRequest(transaction.objectStore(model).delete(key));
                    for (const [model, records] of Object.entries(rows)) {
                        for (const record of records) {
                            guardRequest(transaction.objectStore(model).put(JSON.parse(JSON.stringify(record))));
                        }
                    }
                } catch (error) {
                    abort(error);
                }
            });
        });
    },

    _baseerSamePreparationIds(records, ids) {
        return Array.isArray(records) && Array.isArray(ids) && records.length === ids.length
            && new Set(ids).size === ids.length && new Set(records.map((record) => record.id)).size === records.length
            && records.every((record) => Number.isInteger(record.id) && record.id > 0 && ids.includes(record.id));
    },

    _baseerValidPreparationSnapshot(snapshot, order, status) {
        const records = snapshot?.["pos.order"];
        if (!Array.isArray(records) || records.length !== 1) return false;
        const canonical = records[0];
        if (canonical.id !== order.id || canonical.uuid !== order.uuid
            || canonical.company_id !== order.company_id.id || canonical.config_id !== order.config_id.id) return false;
        for (const model of ["pos.order", "pos.order.line", "pos.payment"]) {
            if (!Array.isArray(snapshot[model]) || snapshot[model].some((record) =>
                !Number.isInteger(record.id) || !record.uuid
                || (this.data.fields[model] || []).some((field) => !Object.hasOwn(record, field)))) return false;
        }
        for (const [model, relation, inverse] of [
            ["pos.order.line", "lines", "order_id"], ["pos.payment", "payment_ids", "pos_order_id"],
        ]) {
            if (!this._baseerSamePreparationIds(snapshot[model], canonical[relation])
                || snapshot[model].some((record) => record[inverse] !== order.id)) return false;
        }
        for (const [model, relation] of [["pos.pack.operation.lot", "pack_lot_ids"],
            ["product.attribute.custom.value", "custom_attribute_value_ids"]]) {
            const children = snapshot[model];
            if (!Array.isArray(children)) return false;
            const ids = snapshot["pos.order.line"].flatMap((line) => line[relation] || []);
            if (!this._baseerSamePreparationIds(children, ids)
                || children.some((child) => !snapshot["pos.order.line"].some((line) =>
                    line.id === child.pos_order_line_id && line[relation]?.includes(child.id)))) return false;
        }
        if (this.models["restaurant.order.course"]) {
            const courses = snapshot["restaurant.order.course"];
            if (!Array.isArray(courses) || !this._baseerSamePreparationIds(courses, canonical.course_ids)
                || courses.some((course) => course.order_id !== order.id
                    || !Array.isArray(course.line_ids) || course.line_ids.some((id) =>
                        !snapshot["pos.order.line"].some((line) => line.id === id && line.course_id === course.id)))
                || snapshot["pos.order.line"].some((line) => line.course_id
                    && !courses.some((course) => course.id === line.course_id && course.line_ids.includes(line.id)))) return false;
        }
        if (canonical.state === "draft") return true;
        // An accepted cancellation of the last kitchen item can natively close
        // an empty order. Never resurrect its previous quantities to unlock it.
        if (canonical.state !== "cancel" || status.skipped || canonical.lines.length
            || canonical.payment_ids.length || canonical.account_move || canonical.is_refund
            || ![canonical.amount_total, canonical.amount_paid, canonical.amount_return].every((amount) =>
                typeof amount === "number" && Math.abs(amount) < 0.000001)) return false;
        try {
            const baseline = typeof canonical.last_order_preparation_change === "string"
                ? JSON.parse(canonical.last_order_preparation_change) : canonical.last_order_preparation_change;
            return Boolean(baseline?.lines) && Object.values(baseline.lines).every((line) =>
                Number.isFinite(line.quantity) && Math.abs(line.quantity) < 0.000001);
        } catch {
            return false;
        }
    },

    async syncAllOrders(options = {}) {
        const pending = this.getPendingOrder();
        const requested = options.orders || [...pending.orderToCreate, ...pending.orderToUpdate];
        const blocked = requested.filter(
            (order) => this._baseerPreparationResolutions?.has(order?.uuid)
                || (order?.uiState?.baseerPreparationOutcomeUnknown
                    && (!order._baseerPreparationRetrySync
                        || order._baseerPreparationRetrySync !== order.uiState.baseerPreparationAction?.action_uuid))
        );
        if (blocked.length && options.throw) {
            throw new Error(_t("Confirm the pending kitchen change before payment."));
        }
        return super.syncAllOrders({
            ...options,
            orders: requested.filter((order) => !blocked.includes(order)),
        });
    },

    _baseerNotifyPreparationStatus(status) {
        if (!status?.accepted) {
            return;
        }
        if (status.skipped) {
            this.notification.add(
                _t("Kitchen sending was skipped. You can continue working on this order."),
                { type: "warning" }
            );
        } else if (status.failed) {
            this.notification.add(
                _t("Kitchen printing failed. The order is saved and you can continue working."),
                { type: "warning" }
            );
        } else if (status.pending) {
            this.notification.add(
                _t("Kitchen change was recorded and is waiting for the Windows agent."),
                { type: "warning" }
            );
        } else if (status.done) {
            this.notification.add(
                _t("Kitchen change was accepted by the Windows print queue."),
                { type: "success" }
            );
        }
    },

    async _baseerWatchPreparationStatus(order, action, initialStatus) {
        let status = initialStatus;
        if (!status?.pending) {
            return status;
        }
        // Do not block the cashier. Follow the job through the Agent retry
        // windows and surface a terminal success/failure while this POS is open.
        for (const delayMs of [2000, 5000, 15000, 60000, 300000]) {
            await new Promise((resolve) => setTimeout(resolve, delayMs));
            if (this.data.network.offline) {
                continue;
            }
            try {
                status = await this._baseerPreparationStatus(order, action);
            } catch {
                continue;
            }
            if (status?.done || status?.failed) {
                this._baseerNotifyPreparationStatus(status);
                return status;
            }
            if (!status?.pending) {
                return status;
            }
        }
        return status;
    },

    get baseerCategoryCount() {
        if (!this.config.baseer_direct_print_enabled) {
            return [];
        }
        const bindings = this.config.baseer_preparation_bindings || [];
        if (!bindings.length) {
            return [];
        }

        const categoriesById = new Map(
            bindings.filter((binding) => binding.category_id).map((binding) => [binding.category_id, binding])
        );
        const genericBinding = bindings.find((binding) => !binding.category_id);
        // Native getOrderChanges is normally fed from IoT/Epson printer
        // categories. Feed it the Baseer categories directly so the POS button
        // works without creating a browser printer.
        const order = this.getOrder();
        if (!order) {
            return [];
        }
        const lineChanges = buildBaseerPreparationAction(order, "send").lines.map((change) => ({
            product_id: order.getOrderlines().find((line) => line.uuid === change.line_uuid)?.product_id?.id,
            quantity: change.new_quantity - change.expected_quantity,
        }));
        const counts = {};

        for (const change of Object.values(lineChanges)) {
            const product = this.models["product.product"].get(change.product_id);
            const categories = product?.pos_categ_ids || product?.product_tmpl_id?.pos_categ_ids || [];
            const categoryIds = [
                ...(product?.parentPosCategIds || []),
                ...categories.map((category) => (typeof category === "number" ? category : category.id)),
            ];
            const binding = categoryIds
                .map((categoryId) => categoriesById.get(categoryId))
                .find(Boolean) || genericBinding;
            if (!binding) {
                continue;
            }
            const key = binding.category_id || "baseer-generic";
            const quantity = Math.abs(change.quantity || 0);
            if (!counts[key]) {
                counts[key] = { count: quantity, name: binding.category_name || _t("Kitchen") };
            } else {
                counts[key].count += quantity;
            }
        }
        return Object.values(counts);
    },

    async baseerSendCurrentOrder() {
        const order = this.getOrder();
        if (!this.config.baseer_direct_print_enabled || !order) {
            return;
        }
        if (this.baseerHasPendingProtectedAction?.(order)) {
            this.notification.add(_t("Resolve the pending item change before sending to the kitchen."), { type: "warning" });
            return false;
        }
        if (this.data.network.offline) {
            throw new Error("Baseer direct printing needs an online POS connection before sending to kitchen.");
        }
        if (this.ensureGuestCustomerCount) {
            await this.ensureGuestCustomerCount(order);
        }
        // A brand-new order needs an id before its first auditable preparation
        // action. Existing orders must not be pre-synced here: doing so would
        // save a quantity change before its intent reaches the server.
        if (!order.isSynced) {
            await this.syncAllOrders({ orders: [order], throw: true });
        }
        if (!order.isSynced || !order.id) {
            throw new Error("Baseer direct printing could not synchronize this order before sending to kitchen.");
        }
        // A lost response is not a rejected action: retain its UUID and first
        // query the durable receipt instead of creating a duplicate action.
        if (order.uiState.baseerPreparationOutcomeUnknown || this._baseerPreparationResolutions?.has(order.uuid)) {
            if (await this.baseerResolvePreparationOutcome(order)) {
                return true;
            }
            this.notification.add(_t("The kitchen result is still unknown. Reconnect and check it before retrying."), { type: "warning" });
            return false;
        }
        const action = order.uiState.baseerPreparationAction || buildBaseerPreparationAction(order, "send");
        if (!action.lines.length) {
            this.notification.add(_t("There are no kitchen changes to send."), { type: "info" });
            return false;
        }
        order.uiState.baseerPreparationAction = action;
        try {
            await this.sendOrderInPreparation(order);
            this.addPendingOrder([order.id]);
            return true;
        } finally {
            if (!order.uiState.baseerPreparationOutcomeUnknown && order.uiState.baseerPreparationAction?.action_uuid === action.action_uuid) {
                delete order.uiState.baseerPreparationAction;
                delete order.uiState.baseerPreparationPreviousChange;
            }
            await this.data.synchronizeLocalDataInIndexedDB();
        }
    },

    async _baseerAskCancellationReason(orderCount) {
        const reasonCode = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Kitchen cancellation"),
            list: BASEER_CANCELLATION_REASONS.map(([id, label]) => ({ id, label, item: id })),
        });
        if (!reasonCode) {
            return false;
        }
        let reasonNote = "";
        if (reasonCode === "other") {
            reasonNote = await makeAwaitable(this.dialog, TextInputPopup, {
                title: _t("Describe the cancellation"),
                startingValue: "",
            });
            if (!reasonNote?.trim()) {
                return false;
            }
        }
        return { reasonCode, reasonNote: reasonNote || "" };
    },

    async _baseerCancellationPreview(orderIds, sessionId) {
        return await this.data.silentCall(
            "pos.order", "baseer_preview_preparation_cancellations", [orderIds, sessionId], {}, false
        );
    },

    async beforeDeleteOrder(order) {
        if (order?.uiState?.baseerPreparationOutcomeUnknown || this._baseerPreparationResolutions?.has(order?.uuid)) {
            if (!(await this.baseerResolvePreparationOutcome(order))) return false;
            order = this.models?.["pos.order"]?.getBy("uuid", order.uuid) || order;
        }
        const allowed = await super.beforeDeleteOrder(order);
        if (!allowed || !this.config.baseer_direct_print_enabled || !order?.isSynced || !Number.isInteger(order.id)) {
            return allowed;
        }
        const sessionId = this.config.current_session_id?.id || this.config.current_session_id;
        if (!Number.isInteger(sessionId)) {
            return allowed;
        }
        const preview = await this._baseerCancellationPreview([order.id], sessionId);
        if (!preview?.order_ids?.includes(order.id)) {
            return allowed;
        }
        const cancellation = await this._baseerAskCancellationReason(1);
        if (!cancellation) {
            return false;
        }
        // This transient UI state is created before POS enters deleteOrders,
        // whose asynchronous lock intentionally blocks nested dialogs.
        order.uiState.baseerKitchenCancellation = cancellation;
        return true;
    },

    async deleteOrders(orders, serverIds = [], ignoreChange = false) {
        if (!this.config.baseer_direct_print_enabled) {
            return super.deleteOrders(orders, serverIds, ignoreChange);
        }
        for (const order of orders) {
            if (!(await this.baseerResolvePreparationOutcome(order))) {
                return false;
            }
        }
        orders = orders.map((order) => this.models?.["pos.order"]?.getBy("uuid", order.uuid) || order);
        const localById = new Map(
            orders.filter((order) => order?.isSynced && Number.isInteger(order.id)).map((order) => [order.id, order])
        );
        const requestedIds = [...new Set([
            ...localById.keys(),
            ...serverIds.filter((id) => Number.isInteger(id)),
        ])];
        const sessionId = this.config.current_session_id?.id || this.config.current_session_id;
        if (!requestedIds.length || !Number.isInteger(sessionId)) {
            return super.deleteOrders(orders, serverIds, ignoreChange);
        }
        const preview = await this._baseerCancellationPreview(requestedIds, sessionId);
        const protectedIds = preview?.order_ids || [];
        if (!protectedIds.length) {
            return super.deleteOrders(orders, serverIds, ignoreChange);
        }
        const protectedSet = new Set(protectedIds);
        const protectedOrders = orders.filter((candidate) => protectedSet.has(candidate?.id));
        const reasonsByOrder = Object.fromEntries(
            protectedOrders
                .filter((order) => order.uiState?.baseerKitchenCancellation)
                .map((order) => [String(order.id), {
                    reason_code: order.uiState.baseerKitchenCancellation.reasonCode,
                    reason_note: order.uiState.baseerKitchenCancellation.reasonNote || "",
                }])
        );
        if (Object.keys(reasonsByOrder).length !== protectedIds.length) {
            this.notification.add(
                _t("Open each kitchen order and choose its cancellation reason before closing the session."),
                { type: "warning" }
            );
            return false;
        }
        const result = await this.data.silentCall(
            "pos.order", "baseer_cancel_with_preparation_reasons",
            [protectedIds, sessionId, reasonsByOrder], {}, false
        );
        // The server transaction already cancelled the protected orders. Remove
        // only their local twins; native deleteOrders remains owner of all other
        // orders and therefore cannot issue a second untracked cancellation.
        for (const order of orders.filter((candidate) => protectedSet.has(candidate?.id))) {
            this.removeOrder(order, false);
            this.removePendingOrder(order);
            delete order.uiState.baseerKitchenCancellation;
        }
        const nativeOrders = orders.filter((candidate) => !protectedSet.has(candidate?.id));
        const nativeServerIds = serverIds.filter((id) => !protectedSet.has(id));
        const nativeResult = await super.deleteOrders(nativeOrders, nativeServerIds, ignoreChange);
        this.notification.add(
            result?.pending
                ? _t("Kitchen cancellation was recorded and is waiting for the Windows agent.")
                : _t("Kitchen cancellation was recorded."),
            { type: result?.pending ? "warning" : "success" }
        );
        return nativeResult;
    },

    async printReceipt(options = {}) {
        const order = options.order || this.getOrder();
        // Restaurant Print Bill is a draft preview, not a paid fiscal receipt.
        // Keep Odoo's own draft-bill route and never enqueue it as a final job.
        if (options.printBillActionTriggered) {
            return super.printReceipt(...arguments);
        }
        if (this.config.baseer_direct_print_enabled && this.config.baseer_native_receipt_enabled) {
            if (!order?.isSynced || !order?.id || !["paid", "done"].includes(order.state)) {
                this.notification.add(
                    _t("The order is not finalized. Complete payment and synchronization before printing its final receipt."),
                    { type: "warning" }
                );
                return { successful: false };
            }
            try {
                // A normal POS tab reload can reuse server data from IndexedDB.
                // Refresh the one native company record before taking a fiscal
                // snapshot, so a VAT/address update is not merely server-ready
                // while the rendered original receipt still uses stale values.
                const companyId = order.company_id?.id;
                if (!companyId || order.company?.id !== companyId) {
                    throw new Error(_t("The receipt company does not match the order. Reload POS data before printing."));
                }
                // Omitting fields means the existing native POS field contract,
                // not unrestricted ORM fields; native data.read also hydrates
                // missing relations and refreshes its own IndexedDB records.
                await this.data.read("res.company", [companyId]);
                if (order.company.country_id?.id && !order.company.country_id.code) {
                    await this.data.read("res.country", [order.company.country_id.id]);
                }
                // This is the same original OrderReceipt capture used by Odoo's
                // customer email flow. Always capture the full fiscal receipt.
                // A thermal 80 mm head needs more than the default browser
                // capture width. Keep the Odoo receipt DOM, but capture at its
                // printable dot density before the agent rasterizes it.
                // The 80 mm driver renders roughly 548 thermal dots across
                // its safe print area.  The receipt DOM itself is ~252 CSS px;
                // 2.2 produces a near one-to-one bitmap for the print head.
                // Avoid sending a 302 px image which Windows must enlarge.
                const renderedCanvas = await this.printer.renderer.toCanvas(
                    OrderReceipt,
                    { order, basic_receipt: false },
                    { addClass: "pos-receipt-print p-3", pixelRatio: 2.2 }
                );
                // Keep the persisted snapshot at the 80 mm print-head width,
                // even if a browser applies a different device pixel ratio.
                // This avoids Windows enlarging a low-resolution receipt.
                const thermalWidth = 576;
                const scale = thermalWidth / renderedCanvas.width;
                const canvas = document.createElement("canvas");
                canvas.width = thermalWidth;
                canvas.height = Math.max(1, Math.round(renderedCanvas.height * scale));
                const context = canvas.getContext("2d", { alpha: false });
                context.fillStyle = "#ffffff";
                context.fillRect(0, 0, canvas.width, canvas.height);
                context.imageSmoothingEnabled = true;
                context.imageSmoothingQuality = "high";
                context.drawImage(renderedCanvas, 0, 0, canvas.width, canvas.height);
                const image = canvas.toDataURL("image/jpeg", 0.95)
                    .replace("data:image/jpeg;base64,", "");
                const result = await this.data.call(
                    "pos.order", "baseer_enqueue_native_receipt", [[order.id], image]
                );
                // Odoo uses nb_print to prevent payment edits after a receipt
                // has been issued. The server applies the same lock atomically
                // with enqueue; mirror it immediately in the current POS tab.
                if (!order.nb_print) {
                    const wasDirty = order.isDirty();
                    order.nb_print = 1;
                    if (!wasDirty) {
                        order._dirty = false;
                    }
                }
                this.notification.add(
                    result.state === "done"
                        ? _t("The original Odoo receipt was already accepted by Windows.")
                        : _t("The original Odoo receipt is queued for the Windows printer."),
                    { type: result.state === "done" ? "info" : "success" }
                );
                return { successful: true, queued: result.state !== "done" };
            } catch (error) {
                const reason = error?.data?.message || error?.message;
                this.notification.add(
                    reason
                        ? _t("Payment remains saved. Customer receipt was not printed: %s", reason)
                        : _t("Payment remains saved, but customer receipt printing failed. Retry from the receipt screen or ask a manager to inspect print jobs."),
                    { type: "danger" }
                );
                return { successful: false, error };
            }
        }
        if (this.config.baseer_direct_print_enabled && order?.isSynced) {
            if (!["paid", "done"].includes(order.state)) {
                this.notification.add(_t("The order is not finalized. Complete payment and synchronization before printing its final receipt."), { type: "warning" });
                return { successful: false };
            }
            // Odoo has already enqueued the receipt after native payment. Avoid a
            // second browser/IoT copy only when direct printing is explicitly on.
            try {
                const status = await this.data.call("pos.order", "baseer_customer_receipt_status", [[order.id]]);
                if (!status?.job_id || !["pending", "leased", "done"].includes(status.state)) {
                    this.notification.add(
                        _t("Payment remains saved. Customer receipt was not printed: %s",
                            status?.error || _t("Ask a manager to inspect Print Jobs.")),
                        { type: "danger" }
                    );
                    return { successful: false };
                }
                return { successful: true, queued: status.state !== "done" };
            } catch (error) {
                this.notification.add(_t("Payment remains saved. Receipt status could not be checked."), { type: "warning" });
                return { successful: false, error };
            }
        }
        return super.printReceipt(...arguments);
    },

    async sendOrderInPreparation(order, opts = {}) {
        if (!order) {
            return false;
        }
        const direct = this.config.baseer_direct_print_enabled;
        if (direct && !opts.orderDone && (order.uiState.baseerPreparationOutcomeUnknown
            || this._baseerPreparationResolutions?.has(order.uuid))) {
            return await this.baseerResolvePreparationOutcome(order);
        }
        if (direct && !opts.orderDone && !order.uiState.baseerPreparationAction) {
            // Native payment and native reprint paths reach this generic method
            // without an auditable Baseer intent. Never print or advance the
            // preparation baseline from those implicit paths.
            return false;
        }
        // A direct ticket is server-derived. Do not let an offline iPad appear
        // to send it successfully while no durable server event exists.
        if (direct && !opts.orderDone && !order.isSynced) {
            throw new Error("Baseer direct printing needs an online POS sync before sending to kitchen.");
        }
        // The native method advances the local preparation baseline. Restore it
        // if the server rejects the Baseer event, otherwise a second tap could
        // silently lose the kitchen delta.
        // Odoo keeps this state as an OWL-reactive object. It is replaced by
        // the native update method, so retain its reference for rollback;
        // structuredClone rejects the reactive proxy during order cancellation.
        const previousChange = order.uiState.baseerPreparationPreviousChange
            || JSON.parse(JSON.stringify(order.last_order_preparation_change || { lines: {} }));
        const hasAuditedAction = Boolean(order.uiState.baseerPreparationAction);
        const auditedAction = order.uiState.baseerPreparationAction;
        const stillCurrent = () => !hasAuditedAction || order.uiState.baseerPreparationAction?.action_uuid === auditedAction.action_uuid;
        if (direct && hasAuditedAction) {
            order.uiState.baseerPreparationPreviousChange = previousChange;
            await this.data.synchronizeLocalDataInIndexedDB();
            if (!stillCurrent()) return false;
        }
        try {
            const result = await super.sendOrderInPreparation(order, {
                ...opts,
                byPassPrint: direct || opts.byPassPrint,
            });
            if (direct && !opts.orderDone && hasAuditedAction) {
                if (!stillCurrent()) return false;
                // Native direct-print bypass does not synchronize after it
                // advances the local preparation baseline. Keep the intent on
                // the order until this explicit sync commits the order change,
                // immutable event and print job in one server transaction.
                order._baseerPreparationRetrySync = auditedAction.action_uuid;
                try {
                    await this.syncAllOrders({ orders: [order], throw: true, force: true });
                } finally {
                    if (order._baseerPreparationRetrySync === auditedAction.action_uuid) {
                        delete order._baseerPreparationRetrySync;
                    }
                }
                const status = await this._baseerPreparationStatus(order, auditedAction);
                if (!stillCurrent()) return false;
                if (!status?.accepted) {
                    const error = new Error(_t("The kitchen change has not been acknowledged by the server. Refresh and check the order before retrying."));
                    error.baseerPreparationOutcomeUnknown = true;
                    throw error;
                }
                if (status.skipped) {
                    order.uiState.baseerPreparationOutcomeUnknown = true;
                    if (!(await this.baseerResolvePreparationOutcome(order))) {
                        const error = new Error(_t("The kitchen result is still unknown. Reconnect and check it before retrying."));
                        error.baseerPreparationOutcomeUnknown = true;
                        throw error;
                    }
                    return { successful: true, recovered: true };
                }
                delete order.uiState.baseerPreparationOutcomeUnknown;
                this._baseerNotifyPreparationStatus(status);
                if (status?.pending) {
                    void this._baseerWatchPreparationStatus(order, auditedAction, status);
                }
            }
            return result;
        } catch (error) {
            if (direct) {
                if (!stillCurrent()) return false;
                try {
                    const status = await this._baseerPreparationStatus(order, auditedAction);
                    if (!stillCurrent()) return false;
                    if (status?.accepted) {
                        order.uiState.baseerPreparationOutcomeUnknown = true;
                        error.baseerPreparationOutcomeUnknown = true;
                        if (await this.baseerResolvePreparationOutcome(order)) {
                            if (status.pending) {
                                void this._baseerWatchPreparationStatus(order, auditedAction, status);
                            }
                            return { successful: true, recovered: true };
                        }
                    }
                } catch {
                    // Preserve the original transport/server error below.
                }
                if (!stillCurrent()) return false;
                const definitive = !error.baseerPreparationOutcomeUnknown && ["odoo.exceptions.ValidationError", "odoo.exceptions.AccessError",
                    "odoo.exceptions.UserError"].includes(error?.data?.name);
                if (definitive) {
                    order.last_order_preparation_change = previousChange;
                    delete order.uiState.baseerPreparationOutcomeUnknown;
                } else {
                    // Do not resurrect the pre-action quantity when the server
                    // may already have committed the kitchen cancellation.
                    order.uiState.baseerPreparationOutcomeUnknown = true;
                    error.baseerPreparationOutcomeUnknown = true;
                }
                await this.data.synchronizeLocalDataInIndexedDB();
            }
            throw error;
        }
    },
});
