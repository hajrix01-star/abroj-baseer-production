/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

export class GoogleBusinessDashboard extends Component {
    static template = "baseer_google_business.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            status: "loading", data: false, selectedLocationId: false, syncing: false,
            refreshing: false, chartRange: "daily",
        });
        this._loadRequestId = 0;
        const englishLabels = {
            eyebrow: _t("GOOGLE BUSINESS"),
            title: _t("Google Business overview"),
            description: _t("Read-only Google Business data. Profile actions are not sales or confirmed website visits."),
            location: _t("Google Business location"),
            summary: _t("Google Business summary"),
            allLocations: _t("All available locations"),
            rating: _t("Average rating"),
            reviews: _t("Google reviews"),
            repliedReviews: _t("Replied reviews"),
            responseRate: _t("Reply rate"),
            profileActions: _t("Profile actions — 30 days"),
            days30: _t("30 days"),
            months12: _t("12 months"),
            daily: _t("Daily"),
            monthly: _t("Monthly"),
            impressions: _t("Impressions"),
            websiteClicks: _t("Website clicks"),
            calls: _t("Calls"),
            directions: _t("Directions"),
            analysis: _t("Engagement analysis"),
            reviewQueue: _t("Review queue"),
            noData: _t("No Google Business data is available for the selected location."),
            error: _t("The Google Business dashboard could not be loaded."),
            retry: _t("Retry"),
            sync: _t("Refresh Google data"),
            syncing: _t("Refreshing…"),
            profile: _t("Profile"),
            openReviews: _t("Open reviews"),
            up: _t("up"),
            down: _t("down"),
            flat: _t("unchanged"),
            noBaseline: _t("not comparable yet"),
            lastSync: _t("Last source sync"),
            manual: _t("Manual responses needed"),
            unanswered: _t("Unanswered reviews"),
            chartAria: _t("Google Business impressions over 30 days"),
            refreshed: _t("Google Business data was refreshed."),
            refreshError: _t("Google Business could not be refreshed. Existing data was kept."),
        };
        const arabicLabels = {
            eyebrow: "ملف النشاط التجاري",
            title: "نظرة عامة على نشاطك التجاري في Google",
            description: "بيانات النشاط التجاري للقراءة فقط. تفاعلات الملف ليست مبيعات ولا زيارات مؤكدة للموقع.",
            location: "الموقع التجاري في Google",
            summary: "ملخص النشاط التجاري",
            allLocations: "كل المواقع المتاحة",
            rating: "متوسط التقييم",
            reviews: "التقييمات",
            repliedReviews: "التقييمات التي تم الرد عليها",
            responseRate: "نسبة الردود",
            profileActions: "تفاعلات الملف — آخر 30 يوماً",
            days30: "آخر 30 يوماً",
            months12: "آخر 12 شهراً",
            daily: "يومي",
            monthly: "شهري",
            impressions: "مرات الظهور",
            websiteClicks: "نقرات الموقع",
            calls: "الاتصالات",
            directions: "طلبات الاتجاهات",
            analysis: "تحليل التفاعل",
            reviewQueue: "قائمة التقييمات",
            noData: "لا توجد بيانات للموقع المحدد.",
            error: "تعذر تحميل لوحة النشاط التجاري.",
            retry: "إعادة المحاولة",
            sync: "تحديث البيانات",
            syncing: "جارٍ التحديث…",
            profile: "الملف الشخصي",
            openReviews: "فتح التقييمات",
            up: "ارتفاع",
            down: "انخفاض",
            flat: "دون تغير",
            noBaseline: "لا توجد مقارنة بعد",
            lastSync: "آخر مزامنة للمصدر",
            manual: "ردود يدوية مطلوبة",
            unanswered: "تقييمات بلا رد",
            chartAria: "مرات الظهور خلال آخر 30 يوماً",
            refreshed: "تم تحديث البيانات.",
            refreshError: "تعذر تحديث البيانات. تم الاحتفاظ بالبيانات الحالية.",
        };
        this.labels = (user.lang || "").toLowerCase().startsWith("ar") ? arabicLabels : englishLabels;
        onWillStart(() => this.load());
    }

    async load(locationId = this.state.selectedLocationId) {
        const requestId = ++this._loadRequestId;
        const initialLoad = !this.state.data;
        if (initialLoad) {
            this.state.status = "loading";
        } else {
            this.state.refreshing = true;
        }
        try {
            const data = await this.orm.call("baseer.gbp.location", "get_dashboard_data", [locationId || false]);
            if (requestId !== this._loadRequestId) {
                return;
            }
            this.state.data = data;
            this.state.selectedLocationId = data.selected_location_id || false;
            this.state.status = data.locations.length && data.has_source_data ? "ready" : "empty";
        } catch (_error) {
            if (requestId !== this._loadRequestId) {
                return;
            }
            if (this.state.data) {
                this.notification.add(this.labels.error, { type: "danger" });
            } else {
                this.state.status = "error";
            }
        } finally {
            if (requestId === this._loadRequestId) {
                this.state.refreshing = false;
            }
        }
    }

    async selectLocation(event) {
        const locationId = Number(event.target.value) || false;
        await this.load(locationId);
    }

    setChartRange(range) {
        this.state.chartRange = range;
    }

    async sync() {
        const locationId = this.state.selectedLocationId;
        if (!locationId || this.state.syncing) {
            return;
        }
        this.state.syncing = true;
        try {
            await this.orm.call("baseer.gbp.location", "action_sync_read_only", [[locationId]]);
            this.notification.add(this.labels.refreshed, { type: "success" });
            await this.load(locationId);
        } catch (_error) {
            this.notification.add(this.labels.refreshError, { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    async open(section) {
        const locationId = this.state.selectedLocationId;
        if (!locationId) {
            return;
        }
        const action = await this.orm.call("baseer.gbp.location", "get_dashboard_action", [locationId, section]);
        await this.action.doAction(action);
    }

    trendLabel() {
        const direction = this.state.data?.trend?.direction;
        return {
            up: this.labels.up,
            down: this.labels.down,
            flat: this.labels.flat,
            no_baseline: this.labels.noBaseline,
        }[direction] || this.labels.noBaseline;
    }
}

registry.category("actions").add("baseer_google_business.dashboard", GoogleBusinessDashboard);
