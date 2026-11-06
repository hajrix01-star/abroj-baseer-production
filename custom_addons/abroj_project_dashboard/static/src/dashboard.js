/** @odoo-module **/
import { Component, onWillStart, useState } from '@odoo/owl';
import { _t } from '@web/core/l10n/translation';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { localization } from '@web/core/l10n/localization';

// All timeline coordinates are offsets from the same inclusive UTC day range.
export function timelineLayout(phases, today = new Date(), language = 'en') {
    const day = 86400000;
    const parse = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? Date.parse(value + 'T00:00:00Z') : NaN;
    const dates = phases.flatMap(p => [parse(p.start), parse(p.end)]).filter(Number.isFinite);
    if (!dates.length) return null;
    const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    const start = Math.min(...dates, now), end = Math.max(...dates, now) + day;
    const count = (end - start) / day;
    const width = Math.max(600, Math.min(2000, count * 56));
    const step = Math.max(1, Math.ceil(80 * count / width));
    const position = value => 100 * (value - start) / (end - start);
    const ar = language.toLowerCase().startsWith('ar');
    const weekdays = ar ? ['أحد','إثنين','ثلاثاء','أربعاء','خميس','جمعة','سبت'] : ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    const months = ar ? ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر'] : ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const cells = Array.from({length: count}, (_, i) => {
        const date = new Date(start + i * day);
        return {index: i, left: position(start + i * day), width: position(start + (i + 1) * day) - position(start + i * day), week: date.getUTCDay() === 6,
            month: i === 0 || date.getUTCDate() === 1, text: `${date.getUTCDate()} ${i === 0 || date.getUTCDate() === 1 ? months[date.getUTCMonth()] : weekdays[date.getUTCDay()]}`};
    });
    const monthIndices = cells.filter(c => c.month).map(c => c.index);
    for (const cell of cells) {
        const show = cell.month || (cell.index % step === 0 && monthIndices.every(i => Math.abs(i - cell.index) >= step));
        cell.label = show ? cell.text : '';
    }
    const labelled = cells.filter(c => c.label);
    labelled.forEach((cell, i) => { cell.labelWidth = 100 * ((labelled[i + 1]?.index ?? count) - cell.index); });
    return {cells, width, step, today: now >= start && now < end ? position(now) : null,
        bar(phase) { const a = parse(phase.start), b = parse(phase.end); return Number.isFinite(a) && Number.isFinite(b) && b >= a ? {left: position(a), width: position(b + day) - position(a)} : null; }};
}

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
    get currency() { return _t('SAR'); }
    get categoryLabels() { return {remaining: _t('Remaining'), total: _t('Total'), phase: _t('Phase')}; }
    get cards() {
        const values = this.state.detail || this.state.data.financial_summary || {};
        const missing = _t('No budget');
        return [
            {label: _t('Contract value'), value: values.contract, icon:'▤'},
            {label: _t('Collected from client'), value: values.customer_received, icon:'⇣', sub: `${_t('Left to collect')} ${this.money(values.remaining)}`},
            {label: _t('Spent'), value: values.total_spent, icon:'⚙', sub: `${_t('Actual')} ${this.money(values.actual)} + ${_t('Advances')} ${this.money(values.advance_paid)}`},
            {label: _t('Budget remaining'), value: values.budget_remaining, icon:'◎', sub: !values.budget_available ? missing : values.budget_overrun > 0 ? `${_t('Overrun')} ${this.money(values.budget_overrun)}` : `${_t('of budget')} ${this.money(values.budget)}`, subRed: values.budget_available && values.budget_overrun > 0},
            {label: _t('Project cash available'), value: values.project_cash, icon:'⇄', sub: `${_t('Collected')} ${this.money(values.customer_received)} − ${_t('paid')} ${this.money(values.paid)}`},
            {label: _t('Expected profit'), value: values.projected_profit, icon:'★', sub: _t('Contract value minus the higher of budget or spent')},
        ];
    }
    timeline(phases) { return timelineLayout(phases, new Date(), localization.code || 'en'); }
    bar(phase, layout) { const bar = layout.bar(phase); return bar ? `left:${bar.left}%;width:${bar.width}%` : ''; }
    get todayLabel() { return _t('Today'); }

}
registry.category('actions').add('abroj_project_dashboard', Dashboard);
