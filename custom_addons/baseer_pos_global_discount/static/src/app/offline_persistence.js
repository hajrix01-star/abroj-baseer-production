/** Commit the native POS order, lines and payment records together. */
export async function persistNativeOfflinePaidOrder(data, order) {
    if (!data?.indexedDB?.db || !order?.uuid || !(typeof order.id === 'string' && order.id || Number.isSafeInteger(order.id) && order.id > 0) ||
        order.state !== "paid" || !order.uiState?.baseerOfflineDiscount) {
        throw new Error("The offline payment could not be saved.");
    }
    const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    const lines = order.lines || [];
    const attributes = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((record) => [record.id, record])).values()];
    const snapshot = {
        "pos.order": [serialize(order)],
        "pos.order.line": lines.map(serialize),
        "pos.payment": (order.payment_ids || []).map(serialize),
        "product.attribute.custom.value": attributes.map(serialize),
    };
    const write = () => new Promise((resolve, reject) => {
        let tx;
        try {
            tx = data.indexedDB.db.transaction(Object.keys(snapshot), "readwrite");
            tx.oncomplete = () => resolve();
            tx.onabort = () => reject(tx.error || new Error("Offline payment transaction aborted."));
            tx.onerror = () => {};
            // Delete only stale rows belonging to this order, in the same
            // transaction as the replacement graph. A previous draft used its
            // UUID as local ID before acquiring a numeric server ID.
            const orderIds = new Set([order.id, order.uuid]);
            for (const [model, owner, key] of [
                ["pos.order.line", "order_id", "uuid"],
                ["pos.payment", "pos_order_id", "uuid"],
            ]) {
                const store = tx.objectStore(model);
                const retained = new Set(snapshot[model].map((record) => record[key]));
                const ownedLineIds = new Set();
                const request = store.openCursor();
                request.onsuccess = () => {
                    const cursor = request.result;
                    if (!cursor) {
                        if (model === 'pos.order.line') {
                            const attributes = tx.objectStore('product.attribute.custom.value');
                            const retainedAttributes = new Set(snapshot['product.attribute.custom.value'].map((record) => record.id));
                            const attributeRequest = attributes.openCursor();
                            attributeRequest.onsuccess = () => {
                                const attribute = attributeRequest.result;
                                if (!attribute) return;
                                if ((ownedLineIds.has(attribute.value.pos_order_line_id) || orderIds.has(attribute.value.pos_order_id)) &&
                                    !retainedAttributes.has(attribute.value.id)) attribute.delete();
                                attribute.continue();
                            };
                        }
                        return;
                    }
                    if (orderIds.has(cursor.value[owner])) {
                        // Another live order may already own a moved record,
                        // even though its old IndexedDB row still points here.
                        const live = data.models?.[model]?.getBy?.('uuid', cursor.value.uuid);
                        const liveOwner = model === 'pos.order.line' ? live?.order_id?.id : live?.pos_order_id?.id;
                        if (live && liveOwner && !orderIds.has(liveOwner)) { cursor.continue(); return; }
                        if (model === 'pos.order.line') {
                            if (cursor.value.id !== undefined && cursor.value.id !== null) ownedLineIds.add(cursor.value.id);
                            if (cursor.value.uuid) ownedLineIds.add(cursor.value.uuid);
                        }
                        if (!retained.has(cursor.value[key])) cursor.delete();
                    }
                    cursor.continue();
                };
            }
            for (const [model, records] of Object.entries(snapshot)) {
                const store = tx.objectStore(model);
                for (const record of records) store.put(record);
            }
        } catch (error) {
            if (tx) tx.abort();
            reject(error);
        }
    });
    return data.indexedDBMutex ? data.indexedDBMutex.exec(write) : write();
}
