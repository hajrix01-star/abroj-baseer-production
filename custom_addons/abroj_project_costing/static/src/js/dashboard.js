/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATE_LABELS = {
    draft: "مسودة",
    pricing: "تحت التسعير",
    approved: "معتمد",
    in_progress: "جاري التنفيذ",
    completed: "مكتمل",
    closed: "مغلق",
    cancelled: "ملغي",
};

export class AbrojProjectCostingDashboard extends Component {
    static template = "abroj_project_costing.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: false,
            empty: false,
            projects: [],
            metrics: {
                active: 0, closed: 0, estimated: 0, actual: 0, variance: 0, progress: 0,
                material: 0, auxiliary: 0, labor: 0, lumpSum: 0,
            },
            categoryDistribution: [],
            topLines: [],
            varianceLines: [],
        });
        onWillStart(() => this.loadDashboard());
    }

    async loadDashboard() {
        const activeDomain = [["state", "not in", ["closed", "cancelled"]]];
        try {
            const [active, closed, totals, projects, categoryDistribution, topLines, varianceLines] = await Promise.all([
                this.orm.searchCount("abroj.cost.project", activeDomain),
                this.orm.searchCount("abroj.cost.project", [["state", "=", "closed"]]),
                this.orm.call(
                    "abroj.cost.project",
                    "read_group",
                    [[], [
                        "estimated_total:sum", "actual_total:sum", "variance_amount:sum", "progress:avg",
                        "estimated_material_total:sum", "estimated_auxiliary_total:sum",
                        "estimated_labor_total:sum", "estimated_lump_sum_total:sum",
                    ], []]
                ),
                this.orm.searchRead(
                    "abroj.cost.project",
                    activeDomain,
                    ["name", "state", "agreement_end_date", "estimated_total", "actual_total", "variance_amount", "progress", "write_date"],
                    { order: "write_date desc", limit: 6 }
                ),
                this.orm.call(
                    "abroj.cost.plan.line",
                    "read_group",
                    [[], ["estimated_total:sum"], ["category_id"]]
                ),
                this.orm.searchRead(
                    "abroj.cost.plan.line",
                    [],
                    ["name", "category_id", "estimated_total", "actual_total", "variance_amount"],
                    { order: "estimated_total desc", limit: 5 }
                ),
                this.orm.searchRead(
                    "abroj.cost.plan.line",
                    [["actual_total", ">", 0]],
                    ["name", "category_id", "estimated_total", "actual_total", "variance_amount"],
                    { order: "variance_amount desc", limit: 5 }
                ),
            ]);
            const total = totals[0] || {};
            this.state.empty = active + closed === 0;
            this.state.metrics = {
                active,
                closed,
                estimated: total.estimated_total || 0,
                actual: total.actual_total || 0,
                variance: total.variance_amount || 0,
                progress: total.progress || 0,
                material: total.estimated_material_total || 0,
                auxiliary: total.estimated_auxiliary_total || 0,
                labor: total.estimated_labor_total || 0,
                lumpSum: total.estimated_lump_sum_total || 0,
            };
            this.state.projects = projects;
            this.state.categoryDistribution = categoryDistribution.filter((row) => row.category_id && row.estimated_total);
            this.state.topLines = topLines;
            this.state.varianceLines = varianceLines.filter((line) => line.variance_amount);
        } catch (error) {
            console.error("ABROJ dashboard could not load", error);
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    formatNumber(value) {
        return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value || 0);
    }

    formatPercent(value) {
        return `${this.formatNumber(value)}%`;
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    barWidth(value, entries) {
        const maximum = Math.max(...entries.map((entry) => Number(entry.value || entry.estimated_total || 0)), 1);
        return `${Math.max(3, Math.min(100, (Number(value || 0) / maximum) * 100))}%`;
    }

    categoryName(row) {
        return Array.isArray(row.category_id) ? row.category_id[1] : "بدون فئة";
    }

    varianceClass(value) {
        return value > 0 ? "is-negative" : "is-positive";
    }

    async openProject(project) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "abroj.cost.project",
            res_id: project.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openProjects() {
        await this.action.doAction("abroj_project_costing.action_abroj_project");
    }
}

registry.category("actions").add("abroj_project_costing.dashboard", AbrojProjectCostingDashboard);
