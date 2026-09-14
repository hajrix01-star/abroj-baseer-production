/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const CATALOG_PAGE_SIZE = 48;
const RECENT_PAGE_SIZE = 24;
function newClientToken() {
    return globalThis.crypto.randomUUID();
}

export class ProcurementCatalog extends Component {
    static template = "baseer_procurement_requests.ProcurementCatalog";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.searchTimer = null;
        this.recentSearchTimer = null;
        this.quoteTimer = null;
        this.catalogSequence = 0;
        this.recentSequence = 0;
        this.quoteSequence = 0;
        this.quickProductButton = useRef("quickProductButton");
        this.quickProductDialog = useRef("quickProductDialog");
        this.quickProductName = useRef("quickProductName");
        this.handleWindowKeydown = (event) => {
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
            warehouseId: false, representativePartnerId: false, whatsappNumber: "", saving: false,
            loadingOptions: true, loadingMore: false, quotePending: false, catalogueError: false,
            mobilePane: "products", clientToken: newClientToken(), workspaceTab: "new",
            recentRequests: [], recentSearch: "", recentState: "all", recentOffset: 0,
            recentHasMore: false, recentLoading: false, recentLoadingMore: false, recentError: false,
            existingRequest: false, quoteError: false, selectedProduct: false,
            canCurateCatalog: false, highlights: [], highlightsLoading: false,
            quickProductOpen: false, quickProductName: "", quickProductPrice: "",
            quickProductSaving: false, quickProductError: false,
        });
        onWillStart(async () => {
            try {
                const [page, categories, warehouses, representatives] = await Promise.all([
                    this.orm.call("baseer.procurement.request", "catalog_page", ["", false, 0, CATALOG_PAGE_SIZE]),
                    this.orm.call("baseer.procurement.request", "catalog_categories", []),
                    this.orm.searchRead("stock.warehouse", [], ["name"], { limit: 100 }),
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
                if (requestId) {
                    const request = await this.orm.call("baseer.procurement.request", "cashier_request_cart", [requestId]);
                    this.state.existingRequest = request;
                    this.state.warehouseId = request.warehouse_id;
                    this.state.representativePartnerId = request.representative_partner_id || false;
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
        const dialog = this.quickProductDialog.el;
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
        this.state.representativePartnerId = Number(event.target.value) || false;
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
        const row = this.state.cart.find((line) => line.option_id === option.id);
        if (row) {
            row.quantity = String((Number(row.quantity) || 0) + 1);
        } else {
            this.state.cart.push({
                option_id: option.id, product_id: option.product_id, name: option.product_name,
                unit: option.option_name, packaging: option.packaging_note, image_url: option.image_url, quantity: "1",
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
    }

    remove(line) {
        if (this.state.existingRequest) {
            if (this.isNotReceived(line)) {
                line.quantity = line.requested_quantity;
                line.actual_price = line.last_price;
            } else {
                line.quantity = "0";
                line.actual_price = "0";
            }
            this.scheduleQuote();
            return;
        }
        this.state.cart.splice(this.state.cart.indexOf(line), 1);
        this.scheduleQuote();
    }

    setQuantity(line, value) {
        line.quantity = value;
        this.scheduleQuote();
    }

    setActualPrice(line, value) {
        line.actual_price = value;
        this.scheduleQuote();
    }

    isNotReceived(line) {
        return Boolean(this.state.existingRequest && !(Number(line.quantity) > 0));
    }

    requiresActualPrice(line) {
        return Boolean(this.state.existingRequest && Number(line.quantity) > 0 && !(Number(line.actual_price) > 0));
    }

    get unpricedReceivedLines() {
        return this.state.cart.filter((line) => this.requiresActualPrice(line));
    }

    stepQuantity(line, step) {
        const next = Math.max(0, (Number(line.quantity) || 0) + step);
        if (!next) return this.remove(line);
        line.quantity = String(next);
        this.scheduleQuote();
    }

    scheduleQuote() {
        globalThis.clearTimeout(this.quoteTimer);
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
        const lines = this.state.existingRequest
            ? this.state.cart.map((line) => ({ line_id: line.line_id, actual_qty: line.quantity, actual_price: line.actual_price }))
            : this.state.cart.map((line) => ({ option_id: line.option_id, quantity: line.quantity }));
        try {
            const quote = await this.orm.call(
                "baseer.procurement.request",
                this.state.existingRequest ? "quote_actual_cart" : "quote_catalog_cart",
                this.state.existingRequest ? [this.state.existingRequest.id, lines] : [lines],
            );
            if (sequence === this.quoteSequence) this.state.quote = quote;
        } catch (error) {
            if (sequence === this.quoteSequence) {
                this.state.quote = this.emptyQuote();
                this.state.quoteError = error.message || _t("Could not calculate the purchase total.");
            }
        } finally {
            if (sequence === this.quoteSequence) this.state.quotePending = false;
        }
    }

    quoteLine(line) {
        return this.state.quote.lines.find((item) => this.state.existingRequest
            ? item.line_id === line.line_id
            : item.option_id === line.option_id);
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
        if (!this.state.existingRequest) return _t("Remove item");
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

    get canSave() {
        const representativeReady = this.state.existingRequest || this.state.representativePartnerId;
        return Boolean(this.state.warehouseId && representativeReady && this.state.cart.length &&
            !this.state.saving && !this.state.quotePending && !this.state.quoteError && !this.unpricedReceivedLines.length &&
            this.state.quote.lines.length === this.state.cart.length);
    }

    async saveDraft(openWhatsApp = false) {
        if (!this.canSave) return;
        this.state.saving = true;
        try {
            if (this.state.existingRequest) {
                const requestName = this.state.existingRequest.name;
                await this.orm.call("baseer.procurement.request", "confirm_actual_from_catalog", [
                    this.state.existingRequest.id,
                    this.state.cart.map((line) => ({
                        line_id: line.line_id,
                        actual_qty: line.quantity,
                        actual_price: line.actual_price,
                    })),
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
                this.state.warehouseId, false, false, this.state.clientToken, this.state.representativePartnerId,
            ]);
            this.state.clientToken = newClientToken();
            if (openWhatsApp) {
                const whatsappAction = await this.orm.call("baseer.procurement.request", "action_open_whatsapp", [[id]]);
                await this.action.doAction(whatsappAction);
            }
            await this.action.doAction({ type: "ir.actions.act_window", res_model: "baseer.procurement.request",
                res_id: id, views: [[false, "form"]], view_mode: "form" });
        } catch (error) {
            this.notification.add(error?.data?.arguments?.[0] || error?.data?.message || error.message || _t("Could not save the procurement request."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}
registry.category("actions").add("baseer_procurement_requests.catalog", ProcurementCatalog);

export class ProcurementActualCatalog extends Component {
    static template = "baseer_procurement_requests.ProcurementActualCatalog";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.quoteTimer = null;
        this.quoteSequence = 0;
        this.state = useState({ request: false, lines: [], quote: this.emptyQuote(), quotePending: true, saving: false, mode: "cashier" });
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
            (this.state.quotePending || this.state.quote.lines.length !== this.state.lines.length))) return;
        this.state.saving = true;
        try {
            const action = this.state.mode === "manager_receipt"
                ? await this.orm.call("baseer.procurement.request", "confirm_manager_receipt_from_catalog", [this.state.request.id,
                    this.state.lines.map((line) => ({ line_id: line.id, manager_received_qty: line.manager_received_qty }))])
                : await this.orm.call("baseer.procurement.request", "confirm_actual_from_catalog", [this.state.request.id,
                    this.state.lines.map((line) => ({ line_id: line.id, actual_qty: line.actual_qty, actual_price: line.actual_price }))]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.message || _t("Could not confirm the quantity receipt."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}
registry.category("actions").add("baseer_procurement_requests.actual_catalog", ProcurementActualCatalog);
