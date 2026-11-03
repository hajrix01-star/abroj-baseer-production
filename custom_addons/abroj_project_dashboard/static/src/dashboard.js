/** @odoo-module **/
import { Component, onWillStart, useState } from '@odoo/owl';
import { _t } from '@web/core/l10n/translation';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';

class Dashboard extends Component {
    static template = 'abroj_project_dashboard.Dashboard';
    setup() {
        this.orm = useService('orm');
        this.detail = this.detail.bind(this);
        this.state = useState({ tab: 'overview', filters: {}, data: {projects: [], types: [], managers: [], clients: []}, detail: null });
        onWillStart(() => this.load());
    }
    async load() { this.state.data = await this.orm.call('project.project', 'get_abroj_dashboard_data', [this.state.filters]); }
    async detail(id) { this.state.detail = await this.orm.call('project.project', 'get_abroj_project_detail', [id]); }
    get projects() { return this.state.data.projects; }
    get donutStyle() {
        const colors = ['#1f2a44', '#f28c28', '#30a46c', '#4a6fa5', '#e2a400'];
        let offset = 0;
        const stops = this.state.data.types.map((type, i) => {
            const start = offset;
            offset += this.projects.length ? 100 * this.projects.filter(p => p.type === type.id).length / this.projects.length : 0;
            return `${colors[i]} ${start}% ${offset}%`;
        });
        return `background:conic-gradient(${stops.join(',')});`;
    }
    get overviewCards() {
        const ps = this.projects;
        return [{label:'إجمالي المشاريع', value:ps.length, icon:'▣'}, {label:'المشاريع الجارية', value:ps.filter(p => !p.completed).length, icon:'◉'}, {label:'المشاريع المكتملة', value:ps.filter(p => p.completed).length, icon:'✓'}, {label:'المتأخرة', value:ps.filter(p => p.delayed).length, icon:'⚠'}, {label:'المتعثرة', value:ps.filter(p => p.stalled).length, icon:'⏸'}];
    }
    total(key) { return this.projects.reduce((sum, p) => sum + (p[key] || 0), 0); }
    money(n) { return n == null ? '—' : Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
    get cards() {
        const values = this.state.detail || this.state.data.financial_summary || {};
        const missing = values.budget_available ? '' : _t('Comparison budget is missing');
        return [
            {label: _t('Comparison budget'), value: values.budget_available ? values.budget : null, icon:'◎', note:missing},
            {label: _t('Actual cost'), value:values.actual, icon:'⚙'},
            {label: _t('Over budget'), value:values.over, icon:'⚠', note:missing},
            {label: _t('Expected margin against budget'), value:values.expected_profit, icon:'★', note:missing},
            {label: _t('Recognized revenue'), value:values.recognized_revenue, icon:'▤'},
            {label: _t('Recognized profit / loss'), value:values.recognized_profit, icon:'★'},
            {label: _t('Voucher cash-flow balance'), value:values.liquidity, icon:'⇄'},
        ];
    }
    bar(phase, phases) {
        const dates = phases.flatMap(p => [p.start, p.end]).filter(Boolean).map(d => Date.parse(d));
        if (!dates.length || !phase.start || !phase.end) return '';
        const min = Math.min(...dates, Date.now()), max = Math.max(...dates, Date.now()), span = Math.max(max-min, 86400000);
        return `left:${100*(Date.parse(phase.start)-min)/span}%;width:${Math.max(1, 100*(Date.parse(phase.end)-Date.parse(phase.start))/span)}%`;
    }
    today(phases) {
        const dates = phases.flatMap(p => [p.start, p.end]).filter(Boolean).map(d => Date.parse(d));
        if (!dates.length) return 'left:50%';
        const min = Math.min(...dates, Date.now()), max = Math.max(...dates, Date.now());
        return `left:${100*(Date.now()-min)/Math.max(max-min, 86400000)}%`;
    }
}
registry.category('actions').add('abroj_project_dashboard', Dashboard);
