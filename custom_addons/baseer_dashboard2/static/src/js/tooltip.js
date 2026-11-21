/** @odoo-module **/

// A single tooltip is shared by every visual in a dashboard. The anchor may be
// a DOM element or the screen-space rectangle of an SVG point.
export class DashboardTooltip {
    constructor() {
        this.element = null;
        this.anchor = null;
        this.timer = null;
        this.outside = (event) => {
            if (this.element && !this.element.contains(event.target) && !this.anchor?.contains?.(event.target)) this.close();
        };
        this.escape = (event) => { if (event.key === 'Escape') this.close(); };
        this.scroll = () => this.close();
    }
    ensure(anchor) {
        const root = anchor.closest('.o_bd2') || anchor.ownerDocument.body;
        if (!this.element || !this.element.isConnected || this.element.parentElement !== root) {
            this.destroy();
            this.element = document.createElement('div');
            this.element.className = 'bd2-tooltip';
            this.element.setAttribute('role', 'tooltip');
            this.element.dir = 'rtl';
            root.appendChild(this.element);
            this.element.addEventListener('pointerenter', () => clearTimeout(this.timer));
            this.element.addEventListener('pointerleave', () => this.deferClose());
            document.addEventListener('pointerdown', this.outside, true);
            document.addEventListener('keydown', this.escape);
            window.addEventListener('scroll', this.scroll, true);
            window.addEventListener('resize', this.scroll);
        }
    }
    show(anchor, rows, options = {}) {
        clearTimeout(this.timer);
        this.ensure(anchor);
        this.anchor = anchor;
        this.element.replaceChildren();
        for (const [label, value] of rows) {
            if (value == null || value === '') continue;
            const line = document.createElement('div');
            const name = document.createElement('span');
            const text = document.createElement('bdi');
            name.textContent = label;
            text.textContent = String(value);
            text.dir = 'auto';
            line.append(name, text);
            this.element.append(line);
        }
        if (options.drill) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = 'عرض السجلات';
            button.addEventListener('click', (event) => { event.stopPropagation(); this.close(); options.drill(event); });
            this.element.append(button);
        }
        this.element.hidden = false;
        this.element.style.visibility = 'hidden';
        this.element.style.left = '0px';
        this.element.style.top = '0px';
        const target = options.rect || anchor.getBoundingClientRect();
        const bounds = options.bounds && (options.bounds.getBoundingClientRect?.() || options.bounds);
        this.element.style.maxWidth = '';
        this.element.style.maxHeight = bounds ? `${Math.max(0, Math.min(window.innerHeight - 8, bounds.bottom) - Math.max(8, bounds.top))}px` : '';
        this.element.style.overflowY = bounds ? 'auto' : '';
        let box = this.element.getBoundingClientRect();
        const margin = 8, gap = 8;
        if (options.bounds) {
            const minTop = Math.max(margin, bounds.top);
            const maxBottom = Math.min(window.innerHeight - margin, bounds.bottom);
            const sideWidth = Math.max(window.innerWidth - margin - target.right - gap, target.left - gap - margin);
            if (box.width > sideWidth && target.bottom + gap + box.height > maxBottom && target.top - gap - box.height < minTop) {
                this.element.style.maxWidth = `${Math.max(0, sideWidth)}px`;
                box = this.element.getBoundingClientRect();
            }
            const left = Math.max(margin, Math.min(window.innerWidth - box.width - margin, target.left + target.width / 2 - box.width / 2));
            let top = target.bottom + gap;
            if (top + box.height > maxBottom) top = target.top - box.height - gap;
            if (top < minTop) top = Math.max(minTop, maxBottom - box.height);
            // Keep the guide visible wherever there is room on either side.
            const right = target.right + gap;
            const leftSide = target.left - gap - box.width;
            let x = right + box.width <= window.innerWidth - margin ? right :
                leftSide >= margin ? leftSide : left;
            // If neither side fits, a vertically separated placement still clears the point.
            if (x === left && top < target.bottom && top + box.height > target.top) {
                top = target.bottom + gap + box.height <= maxBottom ? target.bottom + gap : target.top - box.height - gap;
            }
            this.element.style.left = `${x}px`;
            this.element.style.top = `${top}px`;
            this.element.style.visibility = '';
            return;
        }
        const left = Math.max(margin, Math.min(window.innerWidth - box.width - margin, target.left + target.width / 2 - box.width / 2));
        let top = target.top - box.height - gap;
        if (top < margin) top = target.bottom + gap;
        if (top + box.height > window.innerHeight - margin) {
            // On a short viewport try the side of the anchor before clamping.
            top = Math.max(margin, Math.min(window.innerHeight - box.height - margin, target.top));
            const side = target.right + gap + box.width <= window.innerWidth - margin ? target.right + gap : target.left - gap - box.width;
            if (side >= margin) this.element.style.left = `${side}px`;
            else this.element.style.left = `${left}px`;
        } else this.element.style.left = `${left}px`;
        this.element.style.top = `${top}px`;
        this.element.style.visibility = '';
    }
    toggle(anchor, rows, options = {}) {
        if (this.anchor === anchor && this.element && !this.element.hidden) this.close();
        else this.show(anchor, rows, options);
    }
    deferClose() { clearTimeout(this.timer); this.timer = setTimeout(() => this.close(), 100); }
    close() { clearTimeout(this.timer); if (this.element) this.element.hidden = true; this.anchor = null; }
    destroy() {
        this.close();
        this.element?.remove();
        this.element = null;
        document.removeEventListener('pointerdown', this.outside, true);
        document.removeEventListener('keydown', this.escape);
        window.removeEventListener('scroll', this.scroll, true);
        window.removeEventListener('resize', this.scroll);
    }
}
export const dashboardTooltip = new DashboardTooltip();
