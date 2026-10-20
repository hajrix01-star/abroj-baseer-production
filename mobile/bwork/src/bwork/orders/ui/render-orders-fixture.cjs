/** Generate static HTML from actual React TSX and central components, with synthetic engine data.
 * DOM maps React Native hosts for inspection only: no native layout, keyboard, or backend claims.
 * Usage: node src/bwork/orders/ui/render-orders-fixture.cjs <explicit-output-directory>
 */
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve, join } = require('node:path');
const { harness, nodes, byId } = require('./orders-harness.cjs');

const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const flatten = style => !style ? {} : typeof style === 'function' ? flatten(style({ pressed: false })) : Array.isArray(style) ? Object.assign({}, ...style.map(flatten)) : style;
const unitless = new Set(['flex', 'flexGrow', 'flexShrink', 'opacity', 'zIndex', 'fontWeight', 'order']);
function css(style) {
  return Object.entries(flatten(style)).flatMap(([name, value]) => {
    if (value == null || typeof value === 'object' && name !== 'fontVariant') return [];
    if (name === 'writingDirection') name = 'direction';
    if (name === 'fontVariant') return ['font-variant-numeric:tabular-nums'];
    const axis = /^(padding|margin)(Horizontal|Vertical)$/.exec(name);
    if (axis) return (axis[2] === 'Horizontal' ? ['left', 'right'] : ['top', 'bottom']).map(side => `${axis[1]}-${side}:${typeof value === 'number' ? `${value}px` : value}`);
    const property = name.replace(/[A-Z]/g, char => `-${char.toLowerCase()}`);
    return [`${property}:${typeof value === 'number' && !unitless.has(name) ? `${value}px` : value}`];
  }).join(';');
}
function html(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node !== 'object') return escape(node);
  if (Array.isArray(node)) return node.map(html).join('');
  const p = node.props;
  const children = node.type === 'ScrollView' ? `<div style="display:flex;flex-direction:column;min-width:0;${escape(css(p.contentContainerStyle))}">${html(p.children)}</div>` : html(p.children);
  if (node.type === 'Modal' && p.visible === false) return '';
  const tag = ({ Text: 'span', TextInput: 'input', Pressable: 'button', Svg: 'svg', Path: 'path' })[node.type] ?? 'div';
  const base = tag === 'span' ? 'display:block;white-space:pre-wrap;max-width:100%;' : tag === 'svg' || tag === 'path' ? '' : `display:flex;flex-direction:column;min-width:0;flex-shrink:0;${node.type === 'ScrollView' ? 'overflow:auto;' : ''}`;
  const attributes = [`style="${escape(base + css(p.style))}"`];
  if (p.testID) attributes.push(`data-testid="${escape(p.testID)}"`);
  if (p.accessibilityLabel) attributes.push(`aria-label="${escape(p.accessibilityLabel)}"`);
  if (p.accessibilityRole) attributes.push(`role="${escape(p.accessibilityRole)}"`);
  if (p.accessibilityState?.selected != null) attributes.push(`aria-selected="${!!p.accessibilityState.selected}"`);
  if (tag === 'input') { attributes.push(`value="${escape(p.value)}"`, `placeholder="${escape(p.placeholder)}"`); if (p.editable === false) attributes.push('readonly'); }
  if (tag === 'button' && p.disabled) attributes.push('disabled');
  for (const key of ['viewBox', 'width', 'height', 'fill', 'd', 'stroke', 'strokeWidth', 'strokeLinecap', 'strokeLinejoin']) {
    if (p[key] !== undefined && (tag === 'svg' || tag === 'path')) attributes.push(`${key.replace(/(stroke)([A-Z])/g, (_, a, b) => `${a}-${b.toLowerCase()}`)}="${escape(p[key])}"`);
  }
  return `<${tag} ${attributes.join(' ')}>${tag === 'input' ? '' : children}</${tag}>`;
}
const press = (app, label) => app.act(() => {
  const target = nodes(app.render()).find(node => node.type === 'Pressable' && node.props.accessibilityLabel === label);
  if (!target) throw new Error(`Missing button ${label}`);
  target.props.onPress();
});

async function main() {
  if (!process.argv[2]) throw new Error('Provide an explicit output directory.');
  const destination = resolve(process.argv[2]); mkdirSync(destination, { recursive: true });
  const variants = ['catalog', 'cart', 'review'].flatMap(page => ['ar', 'en'].flatMap(language => [320, 900].map(width => [`${page}-${language}${width}`, language, width])))
    .concat([['all-orders-ar390', 'ar', 390], ['receipt-review-ar390', 'ar', 390]]);
  for (const [name, language, width] of variants) {
    const app = harness({ language, selectedCompanyId: 1 }, true, true); app.setWidth(width);
    const products = Array.from({ length: 24 }, (_, index) => ({ ...app.item, id: 81 + index, product_id: 22 + index,
      product_name: language === 'ar' ? `صنف اختبار ${index + 1}` : `Fixture product ${index + 1}`,
      option_name: language === 'ar' ? 'كرتون شراء' : 'Purchase case', uom_name: language === 'ar' ? 'وحدة' : 'Unit' }));
    app.engine.catalog = async () => ({ api_version: 2, items: products, next_after_id: null });
    try {
      await app.flush();
      if (name.startsWith('cart-') || name.startsWith('review-')) {
        for (const item of products.slice(0, 3)) await press(app, `${language === 'ar' ? 'إضافة' : 'Add'} ${item.product_name} ${item.option_name}`);
        await press(app, `${language === 'ar' ? 'مراجعة السلة' : 'Review cart'} (3)`);
        if (name.startsWith('review-')) await press(app, language === 'ar' ? 'مراجعة الطلب' : 'Review order');
      }
      if (name.startsWith('all-orders')) await app.act(() => byId(app.render(), 'orders-tab-allOrders').onPress());
      if (name.startsWith('receipt-review')) {
        await app.act(() => byId(app.render(), 'orders-tab-receiving').onPress());
        await app.act(() => byId(app.render(), 'receipt-row-12').onPress());
        for (const id of [1, 2]) await app.act(() => byId(app.render(), `receipt-price-${id}`).onChangeText('12.34'));
        await press(app, 'مراجعة الاستلام');
      }
      const document = `<!doctype html><html lang="${language}"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${name}</title><style>*{box-sizing:border-box}body{margin:0;background:#f4f7fd;font:16px system-ui,Segoe UI,Tahoma,sans-serif;color:#101b36}button,input{font:inherit;border:0;margin:0}button{cursor:pointer;appearance:none}button:disabled{opacity:.45}svg{flex-shrink:0}main{width:${width}px;height:760px;min-height:0;max-width:100%;margin:auto;display:flex;flex-direction:column}aside{font-size:11px;color:#54697b;padding:16px}</style><main>${html(app.render())}</main><aside>Isolated fixture. Synthetic data. Actual React screen and central components mapped to DOM. Does not establish native Android appearance or connected Odoo behavior.</aside></html>`;
      writeFileSync(join(destination, `${name}.html`), document, 'utf8');
      process.stdout.write(`${join(destination, `${name}.html`)}\n`);
    } finally { await app.unmount(); }
  }
}
main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
