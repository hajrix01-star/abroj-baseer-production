/** @odoo-module **/
import { Component, onWillStart, onWillUnmount, useState } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { user } from '@web/core/user';
import { useService } from '@web/core/utils/hooks';
import { _t } from '@web/core/l10n/translation';
import { standardFieldProps } from '@web/views/fields/standard_field_props';

class Gallery extends Component {
    static template = 'abroj_project_dashboard.Gallery';
    static props = { ...standardFieldProps };
    setup() {
        this.orm = useService('orm');
        this.state = useState({items: [], type: '', phase: '', uploader: '', sort: 'desc', index: -1, scale: 1, rec: 'idle', seconds: 0, recError: ''});
        this.recSession = 0;
        this.types = [['', _t('الكل')], ['image', _t('صور')], ['audio', _t('صوت')], ['note', _t('ملاحظات')], ['file', _t('ملفات')]];
        this.keyHandler = (event) => { if (this.state.index < 0) return; if (event.key === 'Escape') this.close(); if (event.key === 'ArrowRight') this.move(1); if (event.key === 'ArrowLeft') this.move(-1); };
        window.addEventListener('keydown', this.keyHandler);
        this.visibilityHandler = () => { if (document.hidden) this.cancelRecording(); };
        document.addEventListener('visibilitychange', this.visibilityHandler);
        onWillUnmount(() => { window.removeEventListener('keydown', this.keyHandler); document.removeEventListener('visibilitychange', this.visibilityHandler); this.cancelRecording(); });
        onWillStart(() => this.reload());
    }
    async reload() { if (this.props.record.resId) this.state.items = await this.orm.call('project.project', 'get_abroj_gallery', [[this.props.record.resId]]); }
    get timer() { const s = this.state.seconds; return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }
    get recordLabel() { return this.state.rec === 'recording' ? _t('إيقاف التسجيل') : this.state.rec === 'starting' ? _t('جارٍ تشغيل الميكروفون…') : this.state.rec === 'saving' ? _t('جارٍ الحفظ…') : _t('تسجيل صوتي'); }
    toggleRecording() { if (this.state.rec === 'recording') this.stopRecording(); else if (this.state.rec === 'idle') this.startRecording(); }
    releaseStream() { if (this.recTimer) clearInterval(this.recTimer); this.recTimer = null; if (this.stream) this.stream.getTracks().forEach(track => track.stop()); this.stream = null; }
    async startRecording() {
        if (!this.props.record.resId || this.state.rec !== 'idle') return;
        const session = ++this.recSession;
        this.state.rec = 'starting'; this.state.recError = ''; this.state.seconds = 0;
        try {
            if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('unsupported');
            const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
            if (session !== this.recSession) { stream.getTracks().forEach(track => track.stop()); return; }
            this.stream = stream; this.chunks = [];
            const type = ['audio/webm;codecs=opus', 'audio/mp4'].find(x => MediaRecorder.isTypeSupported(x));
            this.recorder = new MediaRecorder(stream, type ? {mimeType: type} : {});
            this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
            this.recorder.start();
            const started = Date.now();
            this.recTimer = setInterval(() => { this.state.seconds = Math.floor((Date.now() - started) / 1000); }, 250);
            this.state.rec = 'recording';
        } catch (_) {
            if (session === this.recSession) { this.releaseStream(); this.state.rec = 'idle'; this.state.recError = _t('تعذر بدء التسجيل. تحقق من إذن الميكروفون والاتصال الآمن.'); }
        }
    }
    stopRecording() {
        const recorder = this.recorder; if (!recorder || recorder.state === 'inactive') return;
        const session = this.recSession; this.state.rec = 'saving';
        recorder.onstop = () => { this.releaseStream(); if (session === this.recSession) this.upload(new Blob(this.chunks, {type: recorder.mimeType || 'audio/webm'})); };
        recorder.stop(); this.recorder = null;
    }
    cancelRecording() { this.recSession++; if (this.recorder && this.recorder.state !== 'inactive') { this.recorder.onstop = null; this.recorder.stop(); } this.recorder = null; this.releaseStream(); if (this.state.rec !== 'saving') this.state.rec = 'idle'; }
    async upload(blob) {
        try {
            const form = new FormData();
            form.append('csrf_token', odoo.csrf_token); form.append('model', 'project.project'); form.append('record_id', String(this.props.record.resId));
            form.append('file', new File([blob], blob.type.includes('mp4') ? 'voice.mp4' : 'voice.webm', {type: blob.type}));
            const response = await fetch('/abroj/app/upload', {method: 'POST', body: form, credentials: 'same-origin'});
            const result = await response.json();
            if (!response.ok || result.error) throw new Error(result.error || 'upload');
            await this.reload();
        } catch (_) { this.state.recError = _t('تعذر حفظ التسجيل الصوتي.'); }
        finally { this.state.rec = 'idle'; this.state.seconds = 0; }
    }
    get phases() { return [...new Map(this.state.items.filter(x => x.phase).map(x => [x.res_id, x.phase]))]; }
    get uploaders() { return [...new Map(this.state.items.filter(x => x.uploader_id).map(x => [x.uploader_id, x.create_uid]))]; }
    get items() { const s = this.state; return s.items.filter(x => (!s.type || x.type === s.type) && (!s.phase || x.res_model === 'project.task' && String(x.res_id) === s.phase) && (!s.uploader || String(x.uploader_id) === s.uploader)).slice().sort((a,b) => ((a.create_date || '').localeCompare(b.create_date || '') || a.id-b.id) * (s.sort === 'asc' ? 1 : -1)); }
    dateParts(value) { if (!value) return {day: '', time: ''}; const instant = new Date(value); if (Number.isNaN(instant.valueOf())) return {day: '', time: ''}; const options = {calendar:'gregory', numberingSystem:'latn', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}; let formatter; try { formatter = new Intl.DateTimeFormat('en-GB', {...options, timeZone: user.context.tz || undefined}); } catch (_) { formatter = new Intl.DateTimeFormat('en-GB', options); } const p = Object.fromEntries(formatter.formatToParts(instant).map(part => [part.type, part.value])); return {day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}`}; }
    dateTime(value) { const {day, time} = this.dateParts(value); return day ? `${day} ${time}` : ''; }
    get groups() { const groups = []; for (const item of this.items) { const day = this.dateParts(item.create_date).day; if (!groups.length || groups[groups.length-1].day !== day) groups.push({day, items: []}); groups[groups.length-1].items.push(item); } return groups; }
    get images() { return this.items.filter(x => x.type === 'image'); }
    get current() { return this.images[this.state.index]; }
    open(item) { this.state.index = this.images.findIndex(x => x.id === item.id); this.state.scale = 1; }
    close() { this.state.index = -1; }
    move(delta) { if (this.images.length) { this.state.index = (this.state.index + delta + this.images.length) % this.images.length; this.state.scale = 1; } }
    zoom(scale) { this.state.scale = Math.max(1, Math.min(5, scale)); }
    wheel(e) { e.preventDefault(); this.zoom(this.state.scale * (e.deltaY < 0 ? 1.15 : 1/1.15)); }
    touchStart(e) { if (e.touches.length === 1) { this.startX = e.touches[0].clientX; this.pinching = false; } else if (e.touches.length === 2) { this.pinching = true; this.distance = Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY); this.startScale = this.state.scale; } }
    touchMove(e) { if (e.touches.length === 2 && this.distance) { e.preventDefault(); this.zoom(this.startScale * Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY)/this.distance); } }
    touchEnd(e) { if (!e.touches.length) { if (!this.pinching && this.state.scale === 1 && Math.abs(e.changedTouches[0].clientX-this.startX)>60) this.move(e.changedTouches[0].clientX < this.startX ? 1 : -1); this.distance = 0; } }
}
registry.category('fields').add('abroj_gallery', { component: Gallery, supportedTypes: ['char'] });
