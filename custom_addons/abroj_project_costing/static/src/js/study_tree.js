/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const PLAN_FIELDS = [
    "name", "node_kind", "parent_id", "category_id", "quantity",
    "estimated_total", "actual_total", "variance_amount", "currency_id", "sequence",
];

export class AbrojStudyTree extends Component {
    static template = "abroj_project_costing.StudyTree";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, error: false, nodes: [], expanded: {} });
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
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const lines = await this.orm.searchRead(
                "abroj.cost.plan.line",
                [["project_id", "=", projectId]],
                PLAN_FIELDS,
                { order: "parent_path, sequence, id", limit: 500 }
            );
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
            if (generation === this.loadGeneration) {
                this.state.nodes = (byParent.get(false) || []).map(attach);
            }
        } catch (error) {
            console.error("ABROJ study tree could not load", error);
            if (generation === this.loadGeneration) {
                this.state.error = true;
            }
        } finally {
            if (generation === this.loadGeneration) {
                this.state.loading = false;
            }
        }
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
}

registry.category("fields").add("abroj_study_tree", {
    component: AbrojStudyTree,
    supportedTypes: ["char"],
});
