/** @odoo-module **/
import { Component, onWillStart, useState } from '@odoo/owl';
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
    money(n) { return Math.round(n || 0).toLocaleString('en-US'); }
    get cards() {
        const ps = this.state.detail ? [this.state.detail] : this.projects;
        const sum = (key) => ps.reduce((a, p) => a + (p[key] || 0), 0);
        const over = sum('actual') - sum('budget');
        return [{label:'الميزانية', value:sum('budget'), icon:'◎'}, {label:'التكلفة الفعلية', value:sum('actual'), icon:'⚙'}, {label:'تجاوز الميزانية', value:Math.max(over, 0), note: over > 0 ? 'تجاوز الميزانية' : `داخل الميزانية · ${sum('over_categories')} بنود متجاوزة`, icon:'⚠'}, {label:'الربح', value:sum('contract') - sum('actual'), icon:'★'}, {label:'السيولة', value:sum('liquidity'), note:'المحصّل − المدفوع', icon:'⇄'}];
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
