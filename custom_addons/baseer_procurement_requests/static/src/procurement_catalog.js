/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useDropdownState } from "@web/core/dropdown/dropdown_hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useSetupAction } from "@web/search/action_hook";
import { Dialog } from "@web/core/dialog/dialog";

const CATALOG_PAGE_SIZE = 48;
const RECENT_PAGE_SIZE = 24;
function newClientToken() {
    return globalThis.crypto.randomUUID();
}

function newReceiptCustodyState() {
    return { context: false, loading: true, error: false, ready: false, amount: "", paymentJournalId: false, movementDate: "" };
}

function receiptCustodyArguments(value) {
    if (!value.context?.required) return [];
    return [{ snapshot: value.context.snapshot, ...(value.context.existing_funded ? {} : {
        amount: value.amount, payment_journal_id: value.paymentJournalId, movement_date: value.movementDate,
    }) }];
}

export class ReceiptCustodyFields extends Component {
    static template = "baseer_procurement_requests.ReceiptCustodyFields";
    static props = { value: Object, requestId: Number, saving: Boolean };

    setup() {
        this.orm = useService("orm");
        this.state = useState(this.props.value);
        this.loadSequence = 0;
        onMounted(() => this.reloadCustody());
        onWillUnmount(() => this.loadSequence++);
    }

    async reloadCustody() {
        if (this.props.saving) return;
        const sequence = ++this.loadSequence;
        this.state.loading = true;
        this.state.ready = false;
        this.state.error = false;
        try {
            const context = await this.orm.call("baseer.procurement.request", "prepare_receipt_custody", [this.props.requestId]);
            if (sequence !== this.loadSequence) return;
            this.state.context = context;
            this.state.amount = "";
            this.state.paymentJournalId = context.payment_points?.length === 1 ? context.payment_points[0].id : false;
            this.state.movementDate = context.movement_date || "";
            if (context.required && !context.existing_funded && !context.payment_points?.length) {
                this.state.error = _t("No approved bank or cash source is available for this company.");
            }
        } catch (error) {
            if (sequence !== this.loadSequence) return;
            this.state.context = false;
            this.state.error = this.custodyErrorMessage(error);
        } finally {
            if (sequence === this.loadSequence) {
                this.state.loading = false;
                this.updateCustodyReady();
            }
        }
    }

    updateCustodyReady() {
        const context = this.state.context;
        this.state.ready = Boolean(!this.state.loading && !this.state.error && context &&
            (!context.required || (context.snapshot && (context.existing_funded ||
                (String(this.state.amount).trim() && this.state.paymentJournalId && this.state.movementDate)))));
    }

    custodyErrorMessage(error) {
        const businessErrors = ["odoo.exceptions.AccessError", "odoo.exceptions.UserError", "odoo.exceptions.ValidationError"];
        const message = error?.data?.arguments?.[0];
        return businessErrors.includes(error?.data?.name) && typeof message === "string" && message.trim()
            ? message : _t("Could not load the representative advance details.");
    }

    setCustodyField(field, value) {
        if (this.props.saving || this.state.loading || this.state.context?.existing_funded) return;
        if (!["amount", "paymentJournalId", "movementDate"].includes(field)) return;
        this.state[field] = field === "paymentJournalId" ? Number(value) || false : value;
        this.updateCustodyReady();
    }

    custodyMoney(text) {
        const context = this.state.context;
        return context.currency_position === "before" ? `${context.currency_symbol} ${text}` : `${text} ${context.currency_symbol}`;
    }
}

export class ProcurementWhatsAppDialog extends Component {
    static template = "baseer_procurement_requests.WhatsAppShareDialog";
    static components = { Dialog };
    static props = { close: Function, payload: Object, onOpened: { type: Function, optional: true } };

    setup() {
        this.notification = useService("notification");
        this.state = useState({ copyStatus: "" });
    }

    get title() {
        return _t("Share purchase request");
    }

    async recordOpened() {
        // The real anchor navigates directly on the gesture. Audit must not delay it.
        try {
            // The audit can finish after this dialog is closed or the app is backgrounded.
            await this.env.services.orm.call("baseer.procurement.request", "action_mark_whatsapp_opened", [[this.props.payload.request_id]]);
        } catch {
            this.notification.add(_t("Could not record the opening time. You can still use the share link."), { type: "warning" });
            return;
        }
        await this.props.onOpened?.();
    }

    async copyMessage() {
        try {
            await navigator.clipboard.writeText(this.props.payload.text);
            this.state.copyStatus = _t("Message copied.");
        } catch {
            this.state.copyStatus = _t("Select the message below and copy it manually.");
        }
    }
}

export class ProcurementCatalog extends Component {
    static template = "baseer_procurement_requests.ProcurementCatalog";
    static props = ["*"];
    static components = { Dropdown, DropdownItem, ReceiptCustodyFields };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.catalogAlive = true;
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.searchTimer = null;
        this.recentSearchTimer = null;
        this.quoteTimer = null;
        this.catalogSequence = 0;
        this.recentSequence = 0;
        this.quoteSequence = 0;
        this.quickProductButton = useRef("quickProductButton");
        this.quickProductDialog = useRef("quickProductDialog");
        this.quickProductName = useRef("quickProductName");
        this.cancelDialog = useRef("cancelDialog");
        this.cancelReasonInput = useRef("cancelReasonInput");
        this.cancelOrderButton = useRef("cancelOrderButton");
        this.routeDropdown = useDropdownState();
        this.handleWindowKeydown = (event) => {
            if (this.state.cancelOpen) {
                if (event.key === "Escape") this.closeCancel();
                else if (event.key === "Tab") this.trapQuickProductFocus(event);
                return;
            }
            if (this.routeDropdown.isOpen) {
                if (event.key === "Escape") this.routeDropdown.close();
                return;
            }
            if (this.state.quickProductOpen) {
                if (event.key === "Escape") this.closeQuickProduct();
                else if (event.key === "Tab") this.trapQuickProductFocus(event);
                return;
            }
            if (event.key === "Escape" && this.state.selectedProduct) {
                this.closeProductOptions();
            } else if (event.key === "Escape" && this.state.mobilePane === "cart") {
                this.state.mobilePane = "products";
            }
        };
        this.state = useState({
            options: [], categories: [], warehouses: [], representatives: [], cart: [],
            quote: this.emptyQuote(), search: "", selectedCategoryId: false, offset: 0, hasMore: false,
            warehouseId: false, representativePartnerId: false, purchaseRoute: "representative", whatsappNumber: "", saving: false,
            loadingOptions: true, loadingMore: false, quotePending: false, catalogueError: false,
            mobilePane: "products", clientToken: newClientToken(), workspaceTab: "new",
            recentRequests: [], recentSearch: "", recentState: "all", recentOffset: 0,
            recentHasMore: false, recentLoading: false, recentLoadingMore: false, recentError: false,
            existingRequest: false, editRequest: false, editorBaseline: "", removedLines: [], replacementLine: false,
            cancelOpen: false, cancelReason: "", editorLoading: false, quoteError: false, selectedProduct: false, shareLoading: false,
            canCurateCatalog: false, highlights: [], highlightsLoading: false,
            quickProductOpen: false, quickProductName: "", quickProductPrice: "",
            quickProductSaving: false, quickProductError: false,
            receiptCustody: newReceiptCustodyState(),
        });
        useSetupAction({
            beforeLeave: () => this.allowEditorLeave(),
            beforeUnload: (event) => {
                if (this.editorDirty || this.state.saving) {
                    event.preventDefault();
                    event.returnValue = "";
                }
            },
        });
        onWillStart(async () => {
            try {
                const [page, categories, warehouses, representatives] = await Promise.all([
                    this.orm.call("baseer.procurement.request", "catalog_page", ["", false, 0, CATALOG_PAGE_SIZE]),
                    this.orm.call("baseer.procurement.request", "catalog_categories", []),
                    this.orm.call("baseer.procurement.request", "catalog_warehouses", []),
                    this.orm.call("baseer.procurement.request", "catalog_representatives", []),
                ]);
                this.applyCataloguePage(page, true);
                this.state.canCurateCatalog = Boolean(page.can_curate_catalog);
                this.state.categories = categories;
                this.state.warehouses = warehouses;
                this.state.representatives = representatives;
                this.state.warehouseId = warehouses[0]?.id || false;
                this.state.representativePartnerId = representatives.length === 1 ? representatives[0].id : false;
                const requestId = this.props.action?.params?.request_id;
                const editId = this.props.action?.params?.edit_request_id;
                if (editId) {
                    this.applyEditor(await this.orm.call("baseer.procurement.request", "load_catalog_editor", [editId]));
                } else if (requestId) {
                    const request = await this.orm.call("baseer.procurement.request", "cashier_request_cart", [requestId]);
                    this.state.existingRequest = request;
                    this.state.warehouseId = request.warehouse_id;
                    this.state.representativePartnerId = request.representative_partner_id || false;
                    this.state.purchaseRoute = request.purchase_route || "representative";
                    this.state.cart = request.items.map((line) => ({
                        ...line, requested_quantity: line.quantity, actual_price: line.last_price,
                    }));
                    this.scheduleQuote();
                } else if (this.state.canCurateCatalog) {
                    await this.loadHighlights();
                }
                await this.loadRecentRequests();
            } catch (error) {
                this.state.catalogueError = true;
                this.notification.add(error.message || _t("Could not load the procurement catalogue."), { type: "danger" });
            } finally {
                this.state.loadingOptions = false;
            }
        });
        onMounted(() => globalThis.addEventListener("keydown", this.handleWindowKeydown, true));
        onWillUnmount(() => {
            this.catalogAlive = false;
            globalThis.removeEventListener("keydown", this.handleWindowKeydown, true);
            this.catalogSequence++;
            this.recentSequence++;
            this.quoteSequence++;
            globalThis.clearTimeout(this.searchTimer);
            globalThis.clearTimeout(this.recentSearchTimer);
            globalThis.clearTimeout(this.quoteTimer);
        });
    }

    emptyQuote() {
        return { lines: [], total: "0.00", total_text: "0.00", currency_symbol: "", currency_position: "after" };
    }

    editorLines() {
        return this.state.cart.map((line) => ({
            ...(line.line_id ? { line_id: line.line_id } : {}),
            option_id: line.option_id, quantity: line.quantity, unit_price: line.unit_price,
        }));
    }

    editorFingerprint() {
        return JSON.stringify([this.state.purchaseRoute, this.state.representativePartnerId, this.editorLines()]);
    }

    get editorDirty() {
        return Boolean(this.state.editRequest && this.editorFingerprint() !== this.state.editorBaseline);
    }

    applyEditor(request) {
        globalThis.clearTimeout(this.quoteTimer);
        this.quoteSequence++;
        this.state.existingRequest = false;
        this.state.editRequest = request;
        this.state.cart = request.items.map((line) => ({ ...line }));
        this.state.purchaseRoute = request.purchase_route;
        this.state.representativePartnerId = request.representative_partner_id || false;
        this.state.warehouseId = request.warehouse_id;
        this.state.quote = request.quote;
        this.state.quotePending = false;
        this.state.quoteError = false;
        this.state.removedLines = [];
        this.state.replacementLine = false;
        this.state.selectedProduct = false;
        this.state.editorBaseline = this.editorFingerprint();
    }

    async allowEditorLeave() {
        if (this.state.saving) return Boolean(this.allowSavedRequestNavigation && !this.state.editRequest);
        if (!this.editorDirty) return true;
        return new Promise((resolve) => this.dialog.add(ConfirmationDialog, {
            title: _t("Unsaved order changes"),
            body: _t("Discard your changes and leave the order editor?"),
            confirmLabel: _t("Discard changes"), cancelLabel: _t("Keep editing"),
            confirm: () => resolve(true), cancel: () => resolve(false),
        }));
    }

    async switchWorkspace(tab) {
        if (!(await this.allowEditorLeave())) return;
        this.routeDropdown.close();
        if (this.state.editRequest) {
            this.state.editRequest = false;
            this.state.cart = [];
            this.state.removedLines = [];
            this.state.quote = this.emptyQuote();
            this.state.quoteError = false;
            this.state.quotePending = false;
            this.quoteSequence++;
            globalThis.clearTimeout(this.quoteTimer);
        }
        this.state.workspaceTab = tab;
        if (tab === "recent") await this.loadRecentRequests();
    }

    async openReceipt() {
        if (this.state.saving) return;
        try {
            const action = await this.orm.call("baseer.procurement.request", "open_catalog_receipt", [this.state.editRequest.id]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.message || _t("Could not open this request."), { type: "danger" });
        }
    }

    async openOrderEditor() {
        try {
            this.applyEditor(await this.orm.call("baseer.procurement.request", "load_catalog_editor", [this.state.existingRequest.id]));
        } catch (error) {
            this.notification.add(error.message || _t("Could not open this request."), { type: "danger" });
        }
    }

    async changePackaging(line) {
        if (!this.state.editRequest || this.state.saving || this.state.editorLoading) return;
        const request = this.state.editRequest;
        this.state.editorLoading = true;
        try {
            const options = await this.orm.call("baseer.procurement.request", "catalog_editor_options", [
                request.id, line.product_id, request.snapshot,
            ]);
            if (this.state.editRequest !== request || !this.state.cart.includes(line)) return;
            this.state.replacementLine = line;
            this.state.selectedProduct = { product_name: line.name, options };
        } catch (error) {
            this.notification.add(error.message || _t("Could not load packaging options."), { type: "danger" });
        } finally {
            this.state.editorLoading = false;
        }
    }

    replaceMaterial(line) {
        if (this.state.saving) return;
        this.state.replacementLine = line;
        this.state.mobilePane = "products";
    }

    restoreEditorLine(line) {
        if (this.state.saving) return;
        if (this.state.cart.some((item) => item.product_id === line.product_id)) {
            this.notification.add(_t("This material is already in the order. Edit its existing row."), { type: "warning" });
            return;
        }
        this.state.cart.push({ ...line });
        this.state.removedLines.splice(this.state.removedLines.indexOf(line), 1);
        this.scheduleQuote();
    }

    setPlannedPrice(line, value) {
        if (this.state.saving) return;
        line.unit_price = value;
        this.scheduleQuote();
    }

    async saveEditor() {
        if (!this.state.editRequest || !this.canSave || !this.editorDirty) return;
        this.state.saving = true;
        try {
            const request = await this.orm.call("baseer.procurement.request", "save_catalog_edit", [
                this.state.editRequest.id, this.editorLines(), this.state.purchaseRoute,
                this.state.representativePartnerId, this.state.editRequest.snapshot,
            ]);
            this.applyEditor(request);
            this.notification.add(_t("Order changes were saved."), { type: "success" });
            await this.loadRecentRequests();
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error.message || _t("Could not save order changes."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    async openEditorWhatsApp() {
        if (!this.state.editRequest || this.state.purchaseRoute !== "representative" ||
                this.state.saving || this.state.shareLoading || this.editorDirty) return;
        const requestId = this.state.editRequest.id;
        const fingerprint = this.editorFingerprint();
        this.state.shareLoading = true;
        try {
            const payload = await this.orm.call("baseer.procurement.request", "prepare_catalog_whatsapp", [
                requestId, this.state.editRequest.snapshot,
            ]);
            if (this.state.editRequest?.id !== requestId || this.editorDirty || this.editorFingerprint() !== fingerprint) return;
            this.dialog.add(ProcurementWhatsAppDialog, { payload, onOpened: () => this.refreshSharedEditor(requestId) });
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error.message || _t("Could not prepare the WhatsApp message."), { type: "danger" });
        } finally {
            this.state.shareLoading = false;
        }
    }

    async refreshSharedEditor(requestId) {
        if (this.catalogAlive === false || this.state.editRequest?.id !== requestId || this.editorDirty ||
                this.state.saving || this.state.editorLoading || this.state.selectedProduct || this.state.replacementLine) return;
        try {
            const request = await this.orm.call("baseer.procurement.request", "load_catalog_editor", [requestId]);
            if (this.catalogAlive !== false && this.state.editRequest?.id === requestId && !this.editorDirty &&
                    !this.state.saving && !this.state.editorLoading && !this.state.selectedProduct && !this.state.replacementLine) this.applyEditor(request);
        } catch {
            this.notification.add(_t("The order changed. Reload it before editing."), { type: "warning" });
        }
    }

    async reloadEditor() {
        if (!this.state.editRequest || !(await this.allowEditorLeave())) return;
        try {
            this.applyEditor(await this.orm.call("baseer.procurement.request", "load_catalog_editor", [this.state.editRequest.id]));
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error.message || _t("Could not open this request."), { type: "danger" });
        }
    }

    async cancelEditor() {
        if (!this.state.editRequest || this.state.saving || !this.state.cancelReason.trim()) return;
        this.state.saving = true;
        try {
            await this.orm.call("baseer.procurement.request", "cancel_catalog_edit", [
                this.state.editRequest.id, this.state.editRequest.snapshot, this.state.cancelReason,
            ]);
            this.state.cancelOpen = false;
            this.state.editRequest = false;
            this.state.cart = [];
            this.state.quote = this.emptyQuote();
            this.state.quotePending = false;
            this.state.quoteError = false;
            this.state.workspaceTab = "recent";
            this.quoteSequence++;
            globalThis.clearTimeout(this.quoteTimer);
            await this.loadRecentRequests();
            this.notification.add(_t("The order was cancelled."), { type: "success" });
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error.message || _t("Could not cancel the order."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    openCancel() {
        if (this.state.saving) return;
        this.state.cancelOpen = true;
        this.state.cancelReason = "";
        globalThis.requestAnimationFrame(() => this.cancelReasonInput.el?.focus());
    }

    closeCancel() {
        if (this.state.saving) return;
        this.state.cancelOpen = false;
        globalThis.requestAnimationFrame(() => this.cancelOrderButton.el?.focus());
    }

    groupCatalogueItems(items) {
        const groups = new Map();
        for (const option of items) {
            const group = groups.get(option.product_id);
            if (group) {
                group.options.push(option);
            } else {
                groups.set(option.product_id, { ...option, options: [option] });
            }
        }
        return [...groups.values()];
    }

    applyCataloguePage(page, reset) {
        const incoming = this.groupCatalogueItems(page.items);
        if (reset) {
            this.state.options = incoming;
        } else {
            const groups = new Map(this.state.options.map((product) => [product.product_id, {
                ...product, options: [...product.options],
            }]));
            for (const product of incoming) {
                const current = groups.get(product.product_id);
                if (current) {
                    const known = new Set(current.options.map((option) => option.id));
                    current.options.push(...product.options.filter((option) => !known.has(option.id)));
                } else {
                    groups.set(product.product_id, product);
                }
            }
            this.state.options = [...groups.values()];
        }
        this.state.selectedProduct = false;
        this.state.offset = page.next_offset;
        this.state.hasMore = page.has_more;
        this.state.catalogueError = false;
        if (Object.hasOwn(page, "can_curate_catalog")) {
            this.state.canCurateCatalog = Boolean(page.can_curate_catalog);
        }
    }

    async loadHighlights() {
        if (!this.state.canCurateCatalog || this.state.existingRequest) return;
        this.state.highlightsLoading = true;
        try {
            const response = await this.orm.call(
                "baseer.procurement.request", "catalog_highlights", [12],
            );
            this.state.highlights = this.groupCatalogueItems(response.items);
        } catch (error) {
            this.notification.add(error.message || _t("Could not load catalogue shortcuts."), { type: "warning" });
        } finally {
            this.state.highlightsLoading = false;
        }
    }

    async reloadCategories() {
        this.state.categories = await this.orm.call(
            "baseer.procurement.request", "catalog_categories", [],
        );
    }

    openQuickProduct() {
        if (this.state.editRequest || this.state.existingRequest || this.state.saving) return;
        this.state.quickProductName = "";
        this.state.quickProductPrice = "";
        this.state.quickProductError = false;
        this.state.quickProductOpen = true;
        globalThis.requestAnimationFrame(() => {
            globalThis.requestAnimationFrame(() => this.quickProductName.el?.focus());
        });
    }

    closeQuickProduct() {
        if (this.state.quickProductSaving) return;
        this.state.quickProductOpen = false;
        this.state.quickProductError = false;
        globalThis.requestAnimationFrame(() => this.quickProductButton.el?.focus());
    }

    trapQuickProductFocus(event) {
        const dialog = this.state.cancelOpen ? this.cancelDialog.el : this.quickProductDialog.el;
        if (!dialog) return;
        const focusable = [...dialog.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
        )].filter((element) => element.offsetParent !== null);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    onQuickProductName(event) {
        this.state.quickProductName = event.target.value;
        this.state.quickProductError = false;
    }

    onQuickProductPrice(event) {
        this.state.quickProductPrice = event.target.value;
        this.state.quickProductError = false;
    }

    async createQuickProduct() {
        if (this.state.quickProductSaving) return;
        this.state.quickProductSaving = true;
        this.state.quickProductError = false;
        let result;
        let product;
        try {
            result = await this.orm.call(
                "baseer.procurement.request", "create_quick_catalog_product", [
                    this.state.quickProductName,
                    this.state.quickProductPrice,
                    this.state.selectedCategoryId || false,
                ],
            );
            [product] = this.groupCatalogueItems(result.items);
            if (!product) throw new Error(_t("The product was created but could not be loaded."));
            if (!this.state.search && (!this.state.selectedCategoryId ||
                this.state.selectedCategoryId === product.category_id)) {
                this.state.options = [product, ...this.state.options.filter(
                    (candidate) => candidate.product_id !== product.product_id
                )];
            }
        } catch (error) {
            this.state.quickProductError = error?.data?.arguments?.[0] ||
                error?.data?.message || error.message || _t("Could not create the product.");
            this.state.quickProductSaving = false;
            return;
        }
        this.state.quickProductOpen = false;
        this.state.quickProductName = "";
        this.state.quickProductPrice = "";
        this.state.quickProductSaving = false;
        this.selectProduct(product);
        globalThis.requestAnimationFrame(() => {
            if (!this.state.selectedProduct) this.quickProductButton.el?.focus();
        });
        this.notification.add(
            result.created ? _t("Product created and added to the request.") :
                _t("This product already exists and was added without changing its price."),
            { type: "success" },
        );
        const refreshes = await Promise.allSettled([this.reloadCategories(), this.loadHighlights()]);
        if (refreshes.some((refresh) => refresh.status === "rejected")) {
            this.notification.add(_t("The product was added, but catalogue shortcuts could not be refreshed."), {
                type: "warning",
            });
        }
    }

    applyFavoriteState(productId, isFavorite) {
        for (const collection of [this.state.options, this.state.highlights]) {
            for (const product of collection) {
                if (product.product_id === productId) product.is_favorite = isFavorite;
            }
        }
        if (this.state.selectedProduct?.product_id === productId) {
            this.state.selectedProduct.is_favorite = isFavorite;
        }
    }

    async setFavorite(product) {
        if (product.favoriteSaving) return;
        const desiredState = !product.is_favorite;
        product.favoriteSaving = true;
        try {
            const result = await this.orm.call(
                "baseer.procurement.request", "set_catalog_favorite", [product.product_id, desiredState],
            );
            this.applyFavoriteState(result.product_id, result.is_favorite);
            await this.loadHighlights();
        } catch (error) {
            this.notification.add(error.message || _t("Could not update the favorite."), { type: "danger" });
        } finally {
            product.favoriteSaving = false;
        }
    }

    async loadCatalogue(reset = true, requestedSequence = null) {
        if (!reset && (this.state.loadingOptions || this.state.loadingMore)) return;
        const sequence = reset
            ? (requestedSequence ?? ++this.catalogSequence)
            : this.catalogSequence;
        if (reset) {
            this.state.loadingOptions = true;
            this.state.loadingMore = false;
        } else {
            this.state.loadingMore = true;
        }
        try {
            const page = await this.orm.call("baseer.procurement.request", "catalog_page", [
                this.state.search, this.state.selectedCategoryId || false, reset ? 0 : this.state.offset, CATALOG_PAGE_SIZE,
            ]);
            if (sequence === this.catalogSequence) this.applyCataloguePage(page, reset);
        } catch (error) {
            if (sequence === this.catalogSequence) {
                this.state.catalogueError = true;
                this.notification.add(error.message || _t("Could not search the catalogue."), { type: "danger" });
            }
        } finally {
            if (sequence === this.catalogSequence) {
                this.state.loadingOptions = false;
                this.state.loadingMore = false;
            }
        }
    }

    onSearchInput(event) {
        this.state.search = event.target.value;
        globalThis.clearTimeout(this.searchTimer);
        const sequence = ++this.catalogSequence;
        this.state.loadingOptions = true;
        this.state.loadingMore = false;
        this.searchTimer = globalThis.setTimeout(() => this.loadCatalogue(true, sequence), 220);
    }

    async loadRecentRequests(reset = true, requestedSequence = null) {
        if (!reset && (this.state.recentLoading || this.state.recentLoadingMore)) return;
        const sequence = reset
            ? (requestedSequence ?? ++this.recentSequence)
            : this.recentSequence;
        if (reset) {
            this.state.recentLoading = true;
            this.state.recentLoadingMore = false;
            this.state.recentRequests = [];
            this.state.recentOffset = 0;
            this.state.recentHasMore = false;
        } else {
            this.state.recentLoadingMore = true;
        }
        this.state.recentError = false;
        try {
            const page = await this.orm.call("baseer.procurement.request", "cashier_recent_requests", [
                reset ? 0 : this.state.recentOffset,
                RECENT_PAGE_SIZE,
                this.state.recentSearch,
                this.state.recentState,
            ]);
            if (sequence !== this.recentSequence) return;
            if (reset) {
                this.state.recentRequests = page.items;
            } else {
                const known = new Set(this.state.recentRequests.map((request) => request.id));
                this.state.recentRequests.push(...page.items.filter((request) => !known.has(request.id)));
            }
            this.state.recentOffset = page.next_offset;
            this.state.recentHasMore = page.has_more;
        } catch (error) {
            if (sequence === this.recentSequence) {
                this.state.recentError = true;
                this.notification.add(error.message || _t("Could not load previous requests."), { type: "danger" });
            }
        } finally {
            if (sequence === this.recentSequence) {
                this.state.recentLoading = false;
                this.state.recentLoadingMore = false;
            }
        }
    }

    onRecentSearchInput(event) {
        this.state.recentSearch = event.target.value;
        globalThis.clearTimeout(this.recentSearchTimer);
        const sequence = ++this.recentSequence;
        this.state.recentLoading = true;
        this.state.recentLoadingMore = false;
        this.recentSearchTimer = globalThis.setTimeout(() => this.loadRecentRequests(true, sequence), 220);
    }

    onRecentSearchKeydown(event) {
        if (event.key === "Enter") {
            globalThis.clearTimeout(this.recentSearchTimer);
            const sequence = ++this.recentSequence;
            this.loadRecentRequests(true, sequence);
        }
    }

    onRecentStateChange(event) {
        this.state.recentState = event.target.value || "all";
        globalThis.clearTimeout(this.recentSearchTimer);
        const sequence = ++this.recentSequence;
        this.loadRecentRequests(true, sequence);
    }

    recentStateLabel(request) {
        const labels = {
            draft: _t("Draft"),
            sent: _t("Sent to purchaser"),
            received: _t("Waiting for cashier confirmation"),
            purchased: _t("Completed"),
            cancel: _t("Cancelled"),
        };
        return labels[request.state] || request.state_label || request.state;
    }

    async openRecentRequest(request) {
        if (this.state.saving) return;
        try {
            const action = await this.orm.call("baseer.procurement.request", "open_cashier_request", [request.id]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.message || _t("Could not open this request."), { type: "danger" });
        }
    }

    onSearchKeydown(event) {
        if (event.key === "Enter") {
            globalThis.clearTimeout(this.searchTimer);
            const sequence = ++this.catalogSequence;
            this.loadCatalogue(true, sequence);
        }
    }

    onRepresentativeChange(event) {
        if (this.state.saving) return;
        this.state.representativePartnerId = Number(event.target.value) || false;
        if (this.state.editRequest) this.scheduleQuote();
    }

    onWarehouseChange(event) {
        this.state.warehouseId = Number(event.target.value) || false;
    }

    selectCategory(categoryId) {
        if (this.state.selectedCategoryId === categoryId) return;
        this.state.selectedCategoryId = categoryId;
        globalThis.clearTimeout(this.searchTimer);
        const sequence = ++this.catalogSequence;
        this.state.loadingOptions = true;
        this.state.loadingMore = false;
        this.loadCatalogue(true, sequence);
    }

    add(option) {
        if (this.state.saving) return;
        if (this.state.editRequest) {
            const target = this.state.replacementLine;
            if (target && !this.state.cart.includes(target)) {
                this.state.replacementLine = false;
                return;
            }
            if (target?.option_id === option.id) {
                this.state.replacementLine = false;
                this.state.mobilePane = "cart";
                return;
            }
            const duplicate = this.state.cart.find((line) => line.product_id === option.product_id && line !== target);
            if (duplicate) {
                if (duplicate.option_id === option.id && !target) this.stepQuantity(duplicate, 1);
                else this.notification.add(_t("This material is already in the order. Edit its existing row."), { type: "warning" });
                return;
            }
            const row = {
                ...(target?.line_id ? { line_id: target.line_id } : {}),
                option_id: option.id, product_id: option.product_id, name: option.product_name,
                unit: option.option_name, packaging: option.packaging_note, image_url: option.image_url,
                quantity: target?.quantity || "1", unit_price: option.last_price, currency_symbol: option.currency_symbol,
            };
            if (target) {
                this.state.cart.splice(this.state.cart.indexOf(target), 1, row);
                this.state.mobilePane = "cart";
            }
            else this.state.cart.push(row);
            this.state.replacementLine = false;
            this.scheduleQuote();
            return;
        }
        const row = this.state.cart.find((line) => line.option_id === option.id);
        if (row) {
            this.stepQuantity(row, 1);
            return;
        } else {
            if (this.state.existingRequest && !this.state.existingRequest.can_add_materials) {
                this.notification.add(_t("New materials cannot be added after handover or to a BWork request."), { type: "warning" });
                return;
            }
            this.state.cart.push({
                option_id: option.id, product_id: option.product_id, name: option.product_name,
                unit: option.option_name, packaging: option.packaging_note, image_url: option.image_url, quantity: "1",
                ...(this.state.existingRequest ? {
                    actual_price: option.last_price, last_price: option.last_price,
                    currency_symbol: option.currency_symbol,
                } : {}),
            });
        }
        this.scheduleQuote();
    }

    selectProduct(product) {
        if (product.options.length === 1) {
            this.add(product.options[0]);
            return;
        }
        this.state.selectedProduct = product;
    }

    selectProductOption(option) {
        this.add(option);
        this.state.selectedProduct = false;
    }

    closeProductOptions() {
        this.state.selectedProduct = false;
        this.state.replacementLine = false;
    }

    remove(line) {
        if (this.state.saving) return;
        if (this.state.existingRequest && line.line_id) {
            if (this.isNotReceived(line)) {
                this.restoreReceived(line);
            } else {
                this.markNotReceived(line);
            }
            return;
        }
        const index = this.state.cart.indexOf(line);
        if (index < 0) return;
        if (this.state.editRequest) {
            this.state.removedLines = this.state.removedLines.filter((item) => item.option_id !== line.option_id);
            this.state.removedLines.push({ ...line, quantity: Number(line.quantity) > 0 ? line.quantity : line.editQuantitySnapshot || "1" });
            if (this.state.replacementLine === line) this.state.replacementLine = false;
        }
        this.state.cart.splice(index, 1);
        this.scheduleQuote();
    }

    markNotReceived(line) {
        if (Number(line.quantity) > 0) {
            line.receivedSnapshot = { quantity: line.quantity, actual_price: line.actual_price };
        }
        line.quantity = "0";
        line.actual_price = "0";
        this.scheduleQuote();
    }

    restoreReceived(line) {
        line.quantity = line.receivedSnapshot?.quantity ?? line.requested_quantity;
        line.actual_price = line.receivedSnapshot?.actual_price ?? line.last_price;
        this.scheduleQuote();
    }

    setQuantity(line, value) {
        if (this.state.saving) return;
        if (this.state.editRequest && Number(line.quantity) > 0) line.editQuantitySnapshot = line.quantity;
        const originalReceiptLine = this.state.existingRequest && line.line_id;
        const wasZeroOrBlank = originalReceiptLine && Number(line.quantity) === 0;
        if (originalReceiptLine && Number(line.quantity) > 0) {
            line.receivedSnapshot = { quantity: line.quantity, actual_price: line.actual_price };
        }
        line.quantity = value;
        if (originalReceiptLine && String(value).trim() !== "" && Number(value) === 0) {
            this.markNotReceived(line);
            return;
        }
        if (wasZeroOrBlank && Number(value) > 0) {
            line.actual_price = line.receivedSnapshot?.actual_price ?? line.last_price;
        }
        this.scheduleQuote();
    }

    commitQuantity(line) {
        // Commit zero on blur/change, so typing 0.5 never removes the row mid-input.
        if (String(line.quantity).trim() !== "" && Number(line.quantity) === 0) {
            if (this.state.existingRequest && line.line_id) this.markNotReceived(line);
            else this.remove(line);
        }
    }

    setActualPrice(line, value) {
        line.actual_price = value;
        this.scheduleQuote();
    }

    isNotReceived(line) {
        return Boolean(this.state.existingRequest && line.line_id && String(line.quantity).trim() !== "" && Number(line.quantity) === 0);
    }

    requiresActualPrice(line) {
        return Boolean(this.state.existingRequest && Number(line.quantity) > 0 && !(Number(line.actual_price) > 0));
    }

    get unpricedReceivedLines() {
        return this.state.cart.filter((line) => this.requiresActualPrice(line));
    }

    stepQuantity(line, step) {
        if (this.state.saving) return;
        const current = Number(line.quantity);
        if (String(line.quantity).trim() === "" || !Number.isFinite(current) || current < 0) return;
        if (step < 0 && current === 0) return;
        // Adjust the raw decimal input without introducing binary-float digits.
        // The server still validates quantities and calculates every amount.
        if (!/^\d+(?:\.\d{0,2})?$/.test(String(line.quantity))) return;
        const [whole, fraction = ""] = String(line.quantity).split(".");
        const proposed = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0")) + BigInt(step) * 100n;
        const hundredths = proposed > 0n ? proposed : 0n;
        const decimalPart = String(hundredths % 100n).padStart(2, "0").replace(/0+$/, "");
        const next = `${hundredths / 100n}${decimalPart ? `.${decimalPart}` : ""}`;
        if (this.state.existingRequest && line.line_id && step > 0 &&
                Number(next) > Number(line.maximum_quantity ?? line.requested_quantity)) {
            this.notification.add(_t("The quantity cannot exceed the request's received limit."), { type: "warning" });
            return;
        }
        if (!hundredths) {
            if (this.state.existingRequest && line.line_id) this.markNotReceived(line);
            else this.remove(line);
            return;
        }
        this.setQuantity(line, String(next));
    }

    scheduleQuote() {
        globalThis.clearTimeout(this.quoteTimer);
        // Invalidate in-flight responses immediately, including when the last row is removed.
        this.quoteSequence++;
        if (!this.state.cart.length) {
            this.state.quote = this.emptyQuote();
            this.state.quoteError = false;
            this.state.quotePending = false;
            return;
        }
        this.state.quotePending = true;
        this.quoteTimer = globalThis.setTimeout(() => this.refreshQuote(), 140);
    }

    async refreshQuote() {
        const sequence = ++this.quoteSequence;
        this.state.quoteError = false;
        const lines = this.state.editRequest ? this.editorLines() : this.state.existingRequest
            ? this.receiptLines()
            : this.state.cart.map((line) => ({ option_id: line.option_id, quantity: line.quantity }));
        try {
            const quote = await this.orm.call(
                "baseer.procurement.request",
                this.state.editRequest ? "quote_catalog_edit" : this.state.existingRequest ? "quote_actual_cart" : "quote_catalog_cart",
                this.state.editRequest ? [this.state.editRequest.id, lines, this.state.purchaseRoute,
                    this.state.representativePartnerId, this.state.editRequest.snapshot]
                    : this.state.existingRequest ? [this.state.existingRequest.id, lines] : [lines],
            );
            if (sequence === this.quoteSequence) this.state.quote = quote;
        } catch (error) {
            if (sequence === this.quoteSequence) {
                this.state.quote = this.emptyQuote();
                this.state.quoteError = error?.data?.arguments?.[0] || error.message || _t("Could not calculate the purchase total.");
            }
        } finally {
            if (sequence === this.quoteSequence) this.state.quotePending = false;
        }
    }

    quoteLine(line) {
        return this.state.quote.lines.find((item) => this.state.existingRequest
            ? (line.line_id ? item.line_id === line.line_id : !item.line_id && item.option_id === line.option_id)
            : item.option_id === line.option_id);
    }

    receiptLines() {
        return this.state.cart.map((line) => ({
            ...(line.line_id ? { line_id: line.line_id } : { option_id: line.option_id }),
            actual_qty: line.quantity,
            actual_price: line.actual_price,
        }));
    }

    cartQuantity(productId) {
        return this.state.cart.filter((line) => line.product_id === productId)
            .reduce((total, line) => total + (Number(line.quantity) || 0), 0) || false;
    }

    productInitial(option) {
        return (option.product_name || "?").trim().slice(0, 1).toUpperCase();
    }

    productAriaLabel(product) {
        return product.options.length > 1
            ? _t("%s — choose a size", product.product_name)
            : _t("%s — %s", product.product_name, product.option_name);
    }

    removeLineAriaLabel(line) {
        if (!this.state.existingRequest || !line.line_id) return _t("Remove item");
        return this.isNotReceived(line)
            ? _t("Restore received quantity")
            : _t("Mark not received");
    }

    onImageError(event) {
        event.currentTarget.hidden = true;
    }

    formatMoney(text, symbol, position = "after") {
        if (!symbol) return text || "0.00";
        return position === "before" ? `${symbol} ${text}` : `${text} ${symbol}`;
    }

    moneyText(text) {
        return this.formatMoney(text, this.state.quote.currency_symbol, this.state.quote.currency_position);
    }

    recentMoneyText(request) {
        return this.formatMoney(request.total_text, request.currency_symbol, request.currency_position);
    }

    get purchaseRouteSummary() {
        if (this.state.purchaseRoute === "cash") return _t("Cash");
        if (this.state.purchaseRoute === "bank_transfer") return _t("Bank Transfer");
        const name = this.state.existingRequest?.representative_name ||
            this.state.representatives.find((representative) => representative.id === this.state.representativePartnerId)?.name ||
            (this.state.editRequest?.representative_partner_id === this.state.representativePartnerId && this.state.editRequest.representative_name);
        if (name) return _t("Representative: %s", name);
        return this.state.existingRequest ? _t("Legacy request linked to a purchasing employee") : _t("Choose a representative");
    }

    get canSave() {
        const representativeReady = this.state.existingRequest || this.state.purchaseRoute !== "representative" || this.state.representativePartnerId ||
            (this.state.editRequest?.purchase_route === "representative" && !this.state.editRequest.representative_partner_id && this.state.editRequest.representative_name);
        const custodyReady = !this.state.existingRequest || this.state.receiptCustody.ready;
        return Boolean(this.state.warehouseId && representativeReady && custodyReady && this.state.cart.length &&
            !this.state.saving && !this.state.quotePending && !this.state.quoteError && !this.unpricedReceivedLines.length &&
            this.state.quote.lines.length === this.state.cart.length);
    }

    setPurchaseRoute(route) {
        if (this.state.saving) return;
        if (this.state.existingRequest || !["representative", "cash", "bank_transfer"].includes(route)) return;
        this.state.purchaseRoute = route;
        if (route !== "representative") this.state.representativePartnerId = false;
        if (this.state.editRequest) this.scheduleQuote();
    }

    async saveDraft(openWhatsApp = false) {
        if (this.state.editRequest) return this.saveEditor();
        if (!this.canSave) return;
        this.state.saving = true;
        try {
            if (this.state.existingRequest) {
                const requestName = this.state.existingRequest.name;
                await this.orm.call("baseer.procurement.request", "confirm_actual_from_catalog", [
                    this.state.existingRequest.id,
                    this.receiptLines(),
                    ...receiptCustodyArguments(this.state.receiptCustody),
                ]);
                this.state.existingRequest = false;
                this.state.cart = [];
                this.state.quote = this.emptyQuote();
                this.state.quoteError = false;
                this.state.workspaceTab = "new";
                this.notification.add(_t("Request %s was received.", requestName), { type: "success" });
                await this.loadRecentRequests();
                return;
            }
            const id = await this.orm.call("baseer.procurement.request", "create_from_catalog", [
                this.state.cart.map((line) => ({ option_id: line.option_id, quantity: line.quantity })),
                this.state.warehouseId, false, false, this.state.clientToken, this.state.representativePartnerId, this.state.purchaseRoute,
            ]);
            this.state.clientToken = newClientToken();
            // Creation is committed: never leave this cart available for a second create
            // if sharing or marking sent subsequently fails.
            this.state.cart = [];
            this.state.quote = this.emptyQuote();
            let whatsappAction = false;
            if (openWhatsApp) {
                try {
                    if (this.state.purchaseRoute === "representative") {
                        whatsappAction = await this.orm.call("baseer.procurement.request", "action_open_whatsapp", [[id]]);
                    } else {
                        await this.orm.call("baseer.procurement.request", "action_mark_sent", [[id]]);
                    }
                } catch (error) {
                    this.notification.add(error?.data?.arguments?.[0] || error.message || _t("The request was saved. Open it to retry sharing or sending."), { type: "warning" });
                }
            }
            this.allowSavedRequestNavigation = true;
            if (whatsappAction) {
                // The global action function survives catalogue unmount and opens
                // the dialog after form navigation has closed previous dialogs.
                await this.action.doAction({ ...whatsappAction,
                    params: { ...whatsappAction.params, open_saved_request: true } });
            } else {
                await this.action.doAction({ type: "ir.actions.act_window", res_model: "baseer.procurement.request",
                    res_id: id, views: [[false, "form"]], view_mode: "form" });
            }
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error?.data?.message || error.message || _t("Could not save the procurement request."), { type: "danger" });
        } finally {
            this.allowSavedRequestNavigation = false;
            this.state.saving = false;
        }
    }
}
registry.category("actions").add("baseer_procurement_requests.catalog", ProcurementCatalog);
registry.category("actions").add("baseer_procurement_requests.whatsapp_share", async (env, action) => {
    if (action.params.open_saved_request) {
        await env.services.action.doAction({ type: "ir.actions.act_window", res_model: "baseer.procurement.request",
            res_id: action.params.request_id, views: [[false, "form"]], view_mode: "form" });
    }
    env.services.dialog.add(ProcurementWhatsAppDialog, { payload: action.params });
});

export class ProcurementActualCatalog extends Component {
    static template = "baseer_procurement_requests.ProcurementActualCatalog";
    static props = ["*"];
    static components = { ReceiptCustodyFields };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.quoteTimer = null;
        this.quoteSequence = 0;
        this.state = useState({ request: false, lines: [], quote: this.emptyQuote(), quotePending: true, saving: false, mode: "cashier", receiptCustody: newReceiptCustodyState() });
        onWillStart(async () => {
            const requestId = this.props.action.params.request_id;
            this.state.mode = this.props.action.params.mode || "cashier";
            const [request] = await this.orm.read("baseer.procurement.request", [requestId], ["name", "warehouse_id", "purchaser_id", "requested_total"]);
            const rows = await this.orm.searchRead("baseer.procurement.request.line", [["request_id", "=", requestId]], ["option_id", "requested_qty", "manager_received_qty", "actual_qty", "actual_price"]);
            const options = await this.orm.searchRead("baseer.procurement.purchase.option", [["id", "in", rows.map((row) => row.option_id[0])]], ["name", "product_id", "packaging_note", "last_price", "last_price_at"]);
            const byId = Object.fromEntries(options.map((option) => [option.id, option]));
            this.state.request = request;
            this.state.lines = rows.map((row) => ({ ...row, option: byId[row.option_id[0]],
                actual_qty: String(row.actual_qty || row.manager_received_qty || 0),
                manager_received_qty: String(row.manager_received_qty || row.requested_qty || 0),
                actual_price: String(row.actual_price || byId[row.option_id[0]].last_price || 0) }));
            if (this.state.mode === "manager_receipt") this.state.quotePending = false;
            else await this.refreshQuote();
        });
        onWillUnmount(() => globalThis.clearTimeout(this.quoteTimer));
    }

    emptyQuote() {
        return { lines: [], total: "0.00", total_text: "0.00", currency_symbol: "", currency_position: "after" };
    }

    setActual(line, field, value) {
        line[field] = value;
        globalThis.clearTimeout(this.quoteTimer);
        this.state.quotePending = true;
        this.quoteTimer = globalThis.setTimeout(() => this.refreshQuote(), 140);
    }

    setManagerReceipt(line, value) {
        line.manager_received_qty = value;
    }

    optionLabel(option) {
        return [...new Set([option.name, option.packaging_note].filter(Boolean))].join(" · ");
    }

    async refreshQuote() {
        const sequence = ++this.quoteSequence;
        try {
            const quote = await this.orm.call("baseer.procurement.request", "quote_actual_cart", [this.state.request.id,
                this.state.lines.map((line) => ({ line_id: line.id, actual_qty: line.actual_qty, actual_price: line.actual_price }))]);
            if (sequence === this.quoteSequence) this.state.quote = quote;
        } catch {
            if (sequence === this.quoteSequence) this.state.quote = this.emptyQuote();
        } finally {
            if (sequence === this.quoteSequence) this.state.quotePending = false;
        }
    }

    quoteLine(line) {
        return this.state.quote.lines.find((item) => item.line_id === line.id);
    }

    moneyText(text) {
        const symbol = this.state.quote.currency_symbol;
        if (!symbol) return text || "0.00";
        return this.state.quote.currency_position === "before" ? `${symbol} ${text}` : `${text} ${symbol}`;
    }

    async confirm() {
        if (this.state.saving || (this.state.mode !== "manager_receipt" &&
            (!this.state.receiptCustody.ready || this.state.quotePending || this.state.quote.lines.length !== this.state.lines.length))) return;
        this.state.saving = true;
        try {
            const action = this.state.mode === "manager_receipt"
                ? await this.orm.call("baseer.procurement.request", "confirm_manager_receipt_from_catalog", [this.state.request.id,
                    this.state.lines.map((line) => ({ line_id: line.id, manager_received_qty: line.manager_received_qty }))])
                : await this.orm.call("baseer.procurement.request", "confirm_actual_from_catalog", [this.state.request.id,
                    this.state.lines.map((line) => ({ line_id: line.id, actual_qty: line.actual_qty, actual_price: line.actual_price })),
                    ...receiptCustodyArguments(this.state.receiptCustody)]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error.message || _t("Could not confirm the quantity receipt."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}
registry.category("actions").add("baseer_procurement_requests.actual_catalog", ProcurementActualCatalog);
