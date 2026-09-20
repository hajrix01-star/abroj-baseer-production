/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

export class GoogleAdsDashboard extends Component {
    static template = "baseer_google_ads.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.requestSerial = 0;
        this.state = useState({ status: "loading", data: false, refreshing: false, refreshError: false, selectedConnectionId: false, period: "30", dateFrom: "", dateTo: "", campaignStatus: "ALL", campaignId: false, adStatus: "ALL", timelineGrain: "day", timelineMetric: "cost", comparePrevious: true, tab: "overview", filtersOpen: true });
        this.ar = (user.lang || "").toLowerCase().startsWith("ar");
        this.labels = this.ar ? {
            eyebrow: "إعلانات Google", title: "مركز أداء الإعلانات", description: "قراءة فقط. التحويلات والقيم بيانات مبلّغ عنها من Google وليست مبيعات مؤكدة.", account: "الحساب الإعلاني", period: "الفترة", campaignStatus: "حالة الحملة", campaign: "الحملة", adStatus: "حالة الإعلان", all: "الكل", filters: "الفلاتر", showFilters: "إظهار الفلاتر", hideFilters: "إخفاء الفلاتر", apply: "تطبيق", reload: "تحديث العرض", loading: "جارٍ تحميل تقارير الإعلانات…", error: "تعذر تحميل تقارير Google Ads.", retry: "إعادة المحاولة", custom: "نطاق مخصص", from: "من", to: "إلى",
            today: "اليوم", yesterday: "أمس", days7: "آخر 7 أيام", days30: "آخر 30 يومًا", thisMonth: "الشهر الحالي", lastMonth: "الشهر السابق", thisQuarter: "الربع الحالي", lastQuarter: "الربع السابق", thisYear: "السنة الحالية", lastYear: "السنة السابقة", connection: "الاتصال", lastSync: "آخر مزامنة", coverage: "تغطية الفترة", readOnly: "قراءة فقط", refreshing: "جارٍ تحديث الأرقام…", refreshFailed: "تعذر التحديث؛ ما زالت البيانات السابقة معروضة.", detailsScope: "تفاصيل التبويبات من آخر مزامنة تفصيلية؛ الفلاتر الزمنية تؤثر في الملخص والرسم.",
            impressions: "مرات الظهور", clicks: "النقرات", cost: "الإنفاق", ctr: "نسبة النقر", cpc: "متوسط تكلفة النقرة", cpa: "تكلفة النتيجة", conversions: "تحويلات Google", conversionValue: "قيمة التحويلات المبلّغ عنها", trend: "التسلسل الزمني", metric: "المقياس", comparePrevious: "إظهار مقارنة بالفترة السابقة", currentPeriod: "الفترة الحالية", previousPeriod: "الفترة السابقة المساوية", previousCoverage: "تغطية الفترة السابقة", daily: "يومي", monthly: "شهري", yearly: "سنوي", activeCampaigns: "حملات نشطة", pausedCampaigns: "حملات متوقفة", totalCampaigns: "إجمالي الحملات", alerts: "تنبيهات تحتاج متابعة", latestActivity: "آخر نشاط لحملة نشطة", noActivity: "لا يوجد نشاط محفوظ في الفترة", operational: "الملخص التشغيلي", campaignSummary: "ملخص الحملات", priorityAlerts: "تنبيهات الأولوية", noAlerts: "لا توجد تنبيهات نشطة في البيانات المتاحة.",
            overview: "نظرة عامة", conversionsTab: "التحويلات", campaigns: "الحملات", ads: "الإعلانات", search: "البحث والكلمات", opportunities: "الفرص", segments: "الشرائح", insights: "التحليل والتنبيهات", conversionActions: "إجراءات التحويل", conversionPerformance: "أداء التحويلات", keywords: "الكلمات المفتاحية", searchTerms: "عبارات البحث", smartSearchTerms: "عبارات حملات Smart", pmaxSearchTerms: "عبارات Performance Max", campaignNegatives: "الكلمات السلبية للحملات", adGroupNegatives: "الكلمات السلبية للمجموعات", recommendations: "توصيات Google", optimizationScore: "درجة التحسين", assetGroups: "مجموعات أصول Performance Max", recentChanges: "التغييرات الأخيرة", devices: "الأجهزة", dayHours: "الأيام والساعات", networks: "الشبكات", locations: "المواقع الجغرافية",
            rows: "سجل", visibleRows: "المعروض", synced: "آخر تحديث", emptySection: "لا توجد نتائج محفوظة لهذا القسم ضمن الفلاتر الحالية.", pending: "بانتظار المزامنة", available: "متاح", noDataState: "لا توجد بيانات", limited: "العرض محدود لحماية الأداء", not_supported: "غير مدعوم للحساب الحالي", queryFailed: "تعذر قراءة هذا المصدر من Google", performance: "الأداء", conversion: "التحويلات", value: "القيمة", status: "الحالة", accountLevel: "على مستوى الحساب", insightWatch: "يحتاج متابعة", insightAttention: "يحتاج إجراء", insightRecommendation: "توصية من Google", keywordSpendWithoutConversion: "تكلفة بلا تحويلات مبلّغ عنها", spendWithoutConversion: "إنفاق في النطاق بلا تحويلات مبلّغ عنها", adPolicyOrEligibility: "حالة سياسة الإعلان أو أهليته تحتاج مراجعة", googleRecommendation: "اقتراح صادر من Google", adFilterHint: "يؤثر في جدول الإعلانات وتنبيهات السياسة فقط",
        } : {
            eyebrow: "GOOGLE ADS", title: "Advertising performance center", description: "Read-only. Google-reported conversions and values are not confirmed sales.", account: "Ad account", period: "Period", campaignStatus: "Campaign status", campaign: "Campaign", adStatus: "Ad status", all: "All", filters: "Filters", showFilters: "Show filters", hideFilters: "Hide filters", apply: "Apply", reload: "Refresh view", loading: "Loading advertising reports…", error: "Google Ads reporting could not be loaded.", retry: "Retry", custom: "Custom range", from: "From", to: "To",
            today: "Today", yesterday: "Yesterday", days7: "Last 7 days", days30: "Last 30 days", thisMonth: "This month", lastMonth: "Last month", thisQuarter: "This quarter", lastQuarter: "Last quarter", thisYear: "This year", lastYear: "Last year", connection: "Connection", lastSync: "Last sync", coverage: "Period coverage", readOnly: "Read-only", refreshing: "Refreshing figures…", refreshFailed: "Refresh failed; previous data is still shown.", detailsScope: "Detail tabs use the latest detailed sync; date filters apply to the summary and timeline.",
            impressions: "Impressions", clicks: "Clicks", cost: "Spend", ctr: "CTR", cpc: "Average CPC", cpa: "Cost per result", conversions: "Google conversions", conversionValue: "Google-reported conversion value", trend: "Timeline", metric: "Metric", comparePrevious: "Show previous-period comparison", currentPeriod: "Current period", previousPeriod: "Equal previous period", previousCoverage: "Previous period coverage", daily: "Daily", monthly: "Monthly", yearly: "Yearly", activeCampaigns: "Active campaigns", pausedCampaigns: "Paused campaigns", totalCampaigns: "All campaigns", alerts: "Alerts to review", latestActivity: "Latest active campaign activity", noActivity: "No stored activity in this period", operational: "Operational snapshot", campaignSummary: "Campaign summary", priorityAlerts: "Priority alerts", noAlerts: "No active alerts in available data.",
            overview: "Overview", conversionsTab: "Conversions", campaigns: "Campaigns", ads: "Ads", search: "Search & keywords", opportunities: "Opportunities", segments: "Segments", insights: "Insights & alerts", conversionActions: "Conversion actions", conversionPerformance: "Conversion performance", keywords: "Keywords", searchTerms: "Search terms", smartSearchTerms: "Smart campaign search terms", pmaxSearchTerms: "Performance Max search terms", campaignNegatives: "Campaign negative keywords", adGroupNegatives: "Ad group negative keywords", recommendations: "Google recommendations", optimizationScore: "Optimization score", assetGroups: "Performance Max asset groups", recentChanges: "Recent changes", devices: "Devices", dayHours: "Day and hour", networks: "Networks", locations: "Geographic locations",
            rows: "Records", visibleRows: "Visible", synced: "Last refresh", emptySection: "No stored results match the current filters.", pending: "Pending sync", available: "Available", noDataState: "No data", limited: "Display limited to protect performance", not_supported: "Not supported for this account", queryFailed: "Google could not read this source", performance: "Performance", conversion: "Conversions", value: "Value", status: "Status", accountLevel: "Account-level", insightWatch: "Watch", insightAttention: "Action needed", insightRecommendation: "Google recommendation", keywordSpendWithoutConversion: "Spend without reported conversions", spendWithoutConversion: "Spend in range without reported conversions", adPolicyOrEligibility: "Ad policy or eligibility needs review", googleRecommendation: "Google recommendation", adFilterHint: "Affects the Ads table and policy alerts only",
        };
        onWillStart(() => this.load());
    }
    // Report ranges follow the user's local calendar day.  UTC serialization
    // would otherwise turn an early-Riyadh "today" into yesterday.
    iso(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }
    getDates() {
        if (this.state.period === "custom") return { date_from: this.state.dateFrom, date_to: this.state.dateTo };
        const end = new Date(); const start = new Date(end);
        if (this.state.period === "today") return { date_from: this.iso(start), date_to: this.iso(end) };
        if (this.state.period === "yesterday") { start.setDate(start.getDate() - 1); return { date_from: this.iso(start), date_to: this.iso(start) }; }
        if (this.state.period === "7") start.setDate(end.getDate() - 6);
        else if (this.state.period === "month") start.setDate(1);
        else if (this.state.period === "last_month") { start.setMonth(start.getMonth() - 1, 1); end.setDate(0); }
        else if (this.state.period === "quarter" || this.state.period === "last_quarter") { const q = Math.floor(end.getMonth() / 3); start.setMonth(this.state.period === "last_quarter" ? q * 3 - 3 : q * 3, 1); if (this.state.period === "last_quarter") end.setMonth(q * 3, 0); }
        else if (this.state.period === "year" || this.state.period === "last_year") { const year = end.getFullYear() - (this.state.period === "last_year" ? 1 : 0); start.setFullYear(year, 0, 1); if (this.state.period === "last_year") end.setFullYear(year, 11, 31); }
        else start.setDate(end.getDate() - 29);
        return { date_from: this.iso(start), date_to: this.iso(end) };
    }
    async load() {
        const hasVisibleData = Boolean(this.state.data);
        const requestId = ++this.requestSerial;
        this.state.refreshError = false;
        if (hasVisibleData) this.state.refreshing = true;
        else this.state.status = "loading";
        try {
            const data = await this.orm.call("baseer.gads.dashboard", "get_dashboard_data", [], { connection_id: this.state.selectedConnectionId || false, ...this.getDates(), campaign_status: this.state.campaignStatus, campaign_id: this.state.campaignId || false, ad_status: this.state.adStatus, timeline_grain: this.state.timelineGrain, timeline_metric: this.state.timelineMetric, compare_previous: this.state.comparePrevious });
            if (requestId === this.requestSerial) {
                this.state.data = data;
                this.state.selectedConnectionId = data.selected_connection_id || false;
                this.state.status = "ready";
            }
        } catch (_error) {
            if (requestId === this.requestSerial) {
                if (hasVisibleData) this.state.refreshError = true;
                else this.state.status = "error";
            }
        } finally {
            if (requestId === this.requestSerial) this.state.refreshing = false;
        }
    }
    selectConnection(event) { this.state.selectedConnectionId = Number(event.target.value) || false; this.state.campaignId = false; return this.load(); }
    selectPeriod(event) { this.state.period = event.target.value; return this.load(); }
    selectCampaignStatus(event) { this.state.campaignStatus = event.target.value; this.state.campaignId = false; return this.load(); }
    selectCampaign(event) { this.state.campaignId = event.target.value || false; return this.load(); }
    selectAdStatus(event) { this.state.adStatus = event.target.value; return this.load(); }
    selectTimelineGrain(grain) { this.state.timelineGrain = grain; return this.load(); }
    selectTimelineMetric(event) { this.state.timelineMetric = event.target.value; return this.load(); }
    selectComparison(event) { this.state.comparePrevious = event.target.checked; return this.load(); }
    applyCustomDates() { this.state.period = "custom"; return this.load(); }
    toggleFilters() { this.state.filtersOpen = !this.state.filtersOpen; }
    selectTab(tab) { this.state.tab = tab; }
    selectedConnection() { const connections = this.state.data?.connections || []; return connections.find((connection) => connection.id === this.state.selectedConnectionId) || connections[0] || false; }
    connectionState() { return this.statusLabel(this.selectedConnection()?.state, "connection"); }
    statusLabel(status, kind = "") { const ar = { active: "نشط", pending: "بانتظار النقل الآمن", attention: "يحتاج إلى إعادة تفويض", disabled: "معطّل", ENABLED: "نشطة", PAUSED: "متوقفة", REMOVED: "محذوفة", ELIGIBLE: "مؤهل", APPROVED: "معتمد", DISAPPROVED: "مرفوض", NOT_ELIGIBLE: "غير مؤهل", UNDER_REVIEW: "قيد المراجعة", ELIGIBLE_LIMITED: "مؤهل بقيود" }; if (!status) return kind === "account" ? this.labels.accountLevel : "-"; return this.ar ? (ar[status] || status) : status.replaceAll("_", " "); }
    timelineMetrics() { return [["cost", this.labels.cost], ["impressions", this.labels.impressions], ["clicks", this.labels.clicks], ["ctr", this.labels.ctr], ["cpc", this.labels.cpc], ["google_conversions", this.labels.conversions], ["cpa", this.labels.cpa]]; }
    number(value) { const parsed = parseFloat(value); return Number.isFinite(parsed) ? parsed : null; }
    timelinePoints() {
        const current = new Map((this.state.data?.series || []).map((point) => [point.position, point]));
        const previous = new Map((this.state.comparePrevious ? (this.state.data?.comparison_series || []) : []).map((point) => [point.position, point]));
        const positions = [...new Set([...current.keys(), ...previous.keys()])].sort((first, second) => first - second);
        const metric = this.state.timelineMetric;
        return positions.map((position) => ({
            key: `timeline-${position}`, position,
            current: this.number(current.get(position)?.[metric]), previous: this.number(previous.get(position)?.[metric]),
            currentDate: current.get(position)?.date || "-", previousDate: previous.get(position)?.date || "-",
        }));
    }
    timelineHasData() { return this.timelinePoints().some((point) => point.current !== null || point.previous !== null); }
    timelineMax() { return Math.max(...this.timelinePoints().flatMap((point) => [point.current, point.previous]).filter((value) => value !== null), 1); }
    timelineSpan() { return Math.max(...this.timelinePoints().map((point) => point.position), 1); }
    lineSegments(series) { const segments = []; let segment = []; let previousPosition = false; for (const point of this.timelinePoints()) { const value = point[series]; if (value === null || (previousPosition !== false && point.position !== previousPosition + 1)) { if (segment.length) segments.push(segment.join(" ")); segment = []; } if (value !== null) segment.push(`${this.pointX(point.position)},${this.pointY(value)}`); previousPosition = point.position; } if (segment.length) segments.push(segment.join(" ")); return segments; }
    pointX(position) { return (position / this.timelineSpan()) * 100; }
    pointY(value) { return value === null ? 100 : 100 - ((value / this.timelineMax()) * 92 + 4); }
    formatTimelineValue(value) { return value === null ? "—" : value.toLocaleString(this.ar ? "ar-SA" : "en-US", { maximumFractionDigits: 2 }); }
    tabs() { return [["overview", this.labels.overview], ["conversions", this.labels.conversionsTab], ["campaigns", this.labels.campaigns], ["ads", this.labels.ads], ["search", this.labels.search], ["opportunities", this.labels.opportunities], ["segments", this.labels.segments], ["insights", this.labels.insights]]; }
    campaigns() { const items = this.state.data?.filters?.campaigns || []; return this.state.campaignStatus === "ALL" ? items : items.filter((item) => item.status === this.state.campaignStatus); }
    datasetSections() { const groups = { conversions: [["conversion_actions", this.labels.conversionActions], ["conversion_performance", this.labels.conversionPerformance]], campaigns: [["campaigns", this.labels.campaigns]], ads: [["ads", this.labels.ads]], search: [["keywords", this.labels.keywords], ["search_terms", this.labels.searchTerms], ["smart_search_terms", this.labels.smartSearchTerms], ["pmax_search_terms", this.labels.pmaxSearchTerms], ["campaign_negatives", this.labels.campaignNegatives], ["ad_group_negatives", this.labels.adGroupNegatives]], opportunities: [["opportunities", this.labels.opportunities], ["recommendations", this.labels.recommendations], ["optimization_score", this.labels.optimizationScore], ["pmax_asset_groups", this.labels.assetGroups]], segments: [["devices", this.labels.devices], ["day_hours", this.labels.dayHours], ["networks", this.labels.networks], ["locations", this.labels.locations]], insights: [["insights", this.labels.insights], ["recent_changes", this.labels.recentChanges]] }; return (groups[this.state.tab] || []).map(([key, label]) => ({ key, label, ...(this.state.data?.datasets?.[key] || { state: "pending", rows: [], row_count: 0, source_row_count: 0, last_sync: false }) })); }
    datasetState(state) { const labels = { no_data: this.labels.noDataState, not_supported: this.labels.not_supported, query_failed: this.labels.queryFailed }; return labels[state] || this.labels[state] || this.labels.pending; }
    insightDetail(detail) { const labels = { keyword_spend_without_conversion: this.labels.keywordSpendWithoutConversion, spend_without_conversion: this.labels.spendWithoutConversion, ad_policy_or_eligibility: this.labels.adPolicyOrEligibility, google_recommendation: this.labels.googleRecommendation }; return labels[detail] || detail || ""; }
    insightLevel(level) { const labels = { watch: this.labels.insightWatch, attention: this.labels.insightAttention, recommendation: this.labels.insightRecommendation }; return labels[level] || level || ""; }
}

registry.category("actions").add("baseer_google_ads.dashboard", GoogleAdsDashboard);
