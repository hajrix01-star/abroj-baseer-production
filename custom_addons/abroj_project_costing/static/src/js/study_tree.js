/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class AbrojStudyTree extends Component {
    static template = "abroj_project_costing.StudyTree";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            error: false,
            nodes: [],
            flatNodes: [],
            summary: {},
            expanded: {},
            draggedId: false,
            dropTargetId: false,
            dropAtRoot: false,
        });
        this.loadGeneration = 0;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((nextProps) => this.load(nextProps));
    }

    projectIdFor(props) {
        return props.record.resId;
    }

    get projectId() {
        return this.projectIdFor(this.props);
    }

    async load(props = this.props) {
        const generation = ++this.loadGeneration;
        const projectId = this.projectIdFor(props);
        if (!projectId) {
            this.state.loading = false;
            this.state.error = false;
            this.state.nodes = [];
            this.state.flatNodes = [];
            this.state.summary = {};
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const { lines, summary } = await this.orm.call(
                "abroj.cost.project",
                "get_study_tree_view_data",
                [[projectId]]
            );
            const nodes = this.buildTree(lines);
            if (generation === this.loadGeneration) {
                this.state.nodes = nodes;
                this.state.flatNodes = lines;
                this.state.summary = summary;
            }
        } catch (error) {
            console.error("ABROJ study tree could not load", error);
            if (generation === this.loadGeneration) {
                this.state.error = true;
                this.notification.add("تعذر تحديث دراسة المشروع. حاول مرة أخرى.", { type: "danger" });
            }
        } finally {
            if (generation === this.loadGeneration) {
                this.state.loading = false;
            }
        }
    }

    buildTree(lines) {
        const byParent = new Map();
        for (const line of lines) {
            const parentId = line.parent_id ? line.parent_id[0] : false;
            if (!byParent.has(parentId)) {
                byParent.set(parentId, []);
            }
            byParent.get(parentId).push({ ...line, children: [] });
        }
        const attach = (node) => {
            node.children = byParent.get(node.id) || [];
            node.children.forEach(attach);
            return node;
        };
        return (byParent.get(false) || []).map(attach);
    }

    isExpanded(node) {
        return this.state.expanded[node.id] !== false;
    }

    toggle(node) {
        this.state.expanded[node.id] = !this.isExpanded(node);
    }

    formatAmount(value, currency) {
        const amount = new Intl.NumberFormat("en-US", {
            maximumFractionDigits: 2,
            minimumFractionDigits: 2,
        }).format(value || 0);
        return currency ? `${amount} ${currency[1]}` : amount;
    }

    get totalQuantities() {
        const totals = new Map();
        for (const root of this.state.nodes) {
            for (const quantity of root.quantity_totals || []) {
                const previous = totals.get(quantity.uom_type);
                totals.set(quantity.uom_type, {
                    ...quantity,
                    quantity: (previous?.quantity || 0) + quantity.quantity,
                });
            }
        }
        return [...totals.values()];
    }

    formatQuantities(totals) {
        if (!totals?.length) return "0";
        const formatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });
        return totals.map((total) => `${formatter.format(total.quantity)} ${total.label}`).join(" · ");
    }

    async openForm(context, resId = false) {
        const action = {
            type: "ir.actions.act_window",
            res_model: "abroj.cost.plan.line",
            res_id: resId || false,
            views: [[false, "form"]],
            view_mode: "form",
            target: "new",
            context,
        };
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    async addMainSection() {
        const action = await this.orm.call(
            "abroj.cost.project",
            "action_open_plan_section_form",
            [[this.projectId]]
        );
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    async addChildSection(node) {
        const action = await this.orm.call(
            "abroj.cost.project",
            "action_open_plan_section_form",
            [[this.projectId], node.id]
        );
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    addChild(node) {
        return this.openForm({
            default_project_id: this.projectId,
            default_parent_id: node.id,
            default_node_kind: "item",
        });
    }

    editNode(node) {
        return this.openForm({}, node.id);
    }

    dragStart(node, event) {
        if (node.node_kind !== "section") return;
        this.state.draggedId = node.id;
        this.state.dropTargetId = false;
        this.state.dropAtRoot = false;
        event.dataTransfer?.setData("text/plain", String(node.id));
        if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
    }

    dragEnd() {
        this.state.draggedId = false;
        this.state.dropTargetId = false;
        this.state.dropAtRoot = false;
    }

    allowDrop(node, event) {
        if (this.state.draggedId && this.state.draggedId !== node.id) {
            event.preventDefault();
            event.stopPropagation();
            this.state.dropTargetId = node.id;
            this.state.dropAtRoot = false;
            if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        }
    }

    allowRootDrop(event) {
        if (this.state.draggedId && event.target === event.currentTarget) {
            event.preventDefault();
            this.state.dropTargetId = false;
            this.state.dropAtRoot = true;
            if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        }
    }

    async dropOn(node, event) {
        event.preventDefault();
        event.stopPropagation();
        const sourceId = Number(event.dataTransfer?.getData("text/plain") || this.state.draggedId);
        this.state.draggedId = false;
        this.state.dropTargetId = false;
        this.state.dropAtRoot = false;
        if (!sourceId || sourceId === node.id) return;
        await this.reorderSection(sourceId, node.id);
    }

    async dropAtRoot(event) {
        event.preventDefault();
        const sourceId = Number(event.dataTransfer?.getData("text/plain") || this.state.draggedId);
        this.state.draggedId = false;
        this.state.dropTargetId = false;
        this.state.dropAtRoot = false;
        if (sourceId) await this.reorderSection(sourceId, false);
    }

    siblingNodes(node) {
        const parentId = node.parent_id ? node.parent_id[0] : false;
        return this.state.flatNodes.filter((line) => (line.parent_id ? line.parent_id[0] : false) === parentId);
    }

    async moveUp(node) {
        const siblings = this.siblingNodes(node);
        const index = siblings.findIndex((line) => line.id === node.id);
        if (index > 0) await this.reorderSection(node.id, siblings[index - 1].id);
    }

    async moveDown(node) {
        const siblings = this.siblingNodes(node);
        const index = siblings.findIndex((line) => line.id === node.id);
        if (index >= 0 && index < siblings.length - 1) await this.reorderSection(node.id, siblings[index + 1].id);
    }

    async reorderSection(sourceId, targetId) {
        const generation = this.loadGeneration;
        const projectId = this.projectId;
        try {
            const lines = await this.orm.call(
                "abroj.cost.project",
                "action_reorder_plan_section",
                [[projectId], sourceId, targetId || false]
            );
            if (generation !== this.loadGeneration || projectId !== this.projectId) return;
            this.state.flatNodes = lines;
            this.state.nodes = this.buildTree(lines);
            this.notification.add("تم تحديث ترتيب الأقسام.", { type: "success" });
        } catch (error) {
            if (generation !== this.loadGeneration || projectId !== this.projectId) return;
            console.error("ABROJ study tree reorder failed", error);
            this.notification.add(error?.data?.message || "تعذر تغيير ترتيب القسم.", { type: "danger" });
            await this.load();
        }
    }

    confirmDelete(node) {
        const title = node.node_kind === "section" ? "حذف القسم" : "حذف البند";
        this.dialog.add(ConfirmationDialog, {
            title,
            body: `هل تريد حذف «${node.name}»؟ لا يمكن التراجع عن ذلك.`,
            confirmLabel: "حذف",
            confirmClass: "btn-danger",
            cancelLabel: "إلغاء",
            confirm: () => this.deleteNode(node),
        });
    }

    async deleteNode(node) {
        try {
            await this.orm.call("abroj.cost.project", "action_delete_plan_node", [[this.projectId], node.id]);
            await this.load();
            this.notification.add("تم حذف البند من الدراسة.", { type: "success" });
        } catch (error) {
            console.error("ABROJ study tree delete failed", error);
            this.notification.add(error?.data?.message || "تعذر حذف البند.", { type: "danger" });
        }
    }
}

registry.category("fields").add("abroj_study_tree", {
    component: AbrojStudyTree,
    supportedTypes: ["char"],
});
