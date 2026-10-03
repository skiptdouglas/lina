#!/usr/bin/env node
// Renders the real theme (layout, JSON templates, sections, snippets, locales) with
// LiquidJS and sample data into preview/dist/*.html. Shopify-only tags and filters
// are shimmed just enough for the preview; no Shopify store is needed.
//
//   npm install && npm run build && npm run screenshots

import { Liquid, Tag, Hash } from 'liquidjs';
import { readFile, writeFile, mkdir, cp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as data from './sample-data.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const THEME = join(here, '..', 'theme');
const DIST = join(here, 'dist');

const locale = JSON.parse(await readFile(join(THEME, 'locales/en.default.json'), 'utf8'));
const settingsSchema = JSON.parse(await readFile(join(THEME, 'config/settings_schema.json'), 'utf8'));

// Theme settings = schema defaults (+ preview overrides)
const settings = {};
for (const group of settingsSchema) for (const s of group.settings || []) if ('default' in s) settings[s.id] = s.default;
Object.assign(settings, { shop_url: 'collection-1-64-diecast.html', drops_url: 'drop.html', collector_enabled: true, klaviyo_public_key: 'PREVIEW', bundle_discount_collection: data.collections['display-cases'], bundle_fallback_collection: data.collections['display-cases'], cart_upsell_collection: data.collections['display-cases'] });

const engine = new Liquid({ root: [join(THEME, 'snippets')], extname: '.liquid', strictFilters: false, strictVariables: false, jsTruthy: false });

/* ---------- Filters ---------- */
const lookup = (key) => key.split('.').reduce((o, k) => (o == null ? o : o[k]), locale);
engine.registerFilter('t', (key, ...args) => {
  const vars = Object.fromEntries(args.filter(Array.isArray));
  let v = lookup(key);
  if (v && typeof v === 'object') v = vars.count === 1 ? v.one ?? v.other : v.other;
  if (typeof v !== 'string') return `[missing: ${key}]`;
  return v.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, k) => vars[k] ?? '');
});
const money = (c) => `$${(Number(c || 0) / 100).toFixed(2)}`;
engine.registerFilter('money', money);
engine.registerFilter('money_without_currency', (c) => (Number(c || 0) / 100).toFixed(2));
engine.registerFilter('handleize', (s) => String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''));
engine.registerFilter('asset_url', (f) => `assets/${f}`);
engine.registerFilter('stylesheet_tag', (u) => `<link rel="stylesheet" href="${u}">`);
engine.registerFilter('url_for_vendor', (v) => `collection-1-64-diecast.html?vendor=${encodeURIComponent(v)}`);
engine.registerFilter('image_url', (img) => (img && typeof img === 'object' ? img.src : img || ''));
engine.registerFilter('image_tag', (src, ...args) => {
  const o = Object.fromEntries(args.filter(Array.isArray));
  const attrs = Object.entries(o)
    .filter(([k]) => !['widths', 'sizes'].includes(k))
    .map(([k, v]) => `${k}="${String(v ?? '').replace(/"/g, '&quot;')}"`)
    .join(' ');
  return `<img src="${src}" ${attrs}>`;
});
engine.registerFilter('placeholder_svg_tag', () => '<svg viewBox="0 0 100 100" style="width:100%;height:100%;background:#eceded"></svg>');
engine.registerFilter('metafield_tag', (v) => (v && typeof v === 'object' ? v.value : v));
engine.registerFilter('payment_button', () => '<button type="button" class="button button--full" style="background:#000;margin-top:2px" disabled>Buy with  Pay</button>');
engine.registerFilter('default_errors', () => '');
engine.registerFilter('format_address', () => '<p>12 Ponsonby Road<br>Auckland 1011<br>New Zealand</p>');
engine.registerFilter('weight_with_unit', (g) => `${g} g`);

/* ---------- Tags ---------- */
engine.registerTag('schema', class extends Tag {
  constructor(token, remain, liquid) {
    super(token, remain, liquid);
    while (remain.length) if (remain.shift().name === 'endschema') return;
  }
  * render() {}
});

class BlockTag extends Tag {
  constructor(token, remain, liquid, endName) {
    super(token, remain, liquid);
    this.args = token.args;
    this.tpls = [];
    const stream = liquid.parser.parseStream(remain).on(`tag:${endName}`, () => stream.stop()).on('template', (t) => this.tpls.push(t)).on('end', () => { throw new Error(`${endName} missing`); });
    stream.start();
  }
}
engine.registerTag('form', class extends BlockTag {
  constructor(t, r, l) { super(t, r, l, 'endform'); }
  * render(ctx, emitter) {
    const type = (this.args.match(/^'([^']+)'/) || [])[1];
    const id = (this.args.match(/id:\s*'([^']+)'/) || [])[1];
    const cls = (this.args.match(/class:\s*'([^']+)'/) || [])[1];
    const action = { product: 'cart.html', customer: '#', customer_login: '#', create_customer: '#' }[type] || '#';
    emitter.write(`<form method="post" action="${action}"${id ? ` id="${id}"` : ''}${cls ? ` class="${cls}"` : ''}>`);
    ctx.push({ form: { errors: false, 'posted_successfully?': false } });
    yield this.liquid.renderer.renderTemplates(this.tpls, ctx, emitter);
    ctx.pop();
    emitter.write('</form>');
  }
});
engine.registerTag('paginate', class extends BlockTag {
  constructor(t, r, l) { super(t, r, l, 'endpaginate'); }
  * render(ctx, emitter) {
    ctx.push({ paginate: { pages: 1, current_page: 1, parts: [] }, current_page: 1 });
    yield this.liquid.renderer.renderTemplates(this.tpls, ctx, emitter);
    ctx.pop();
  }
});
engine.registerTag('style', class extends BlockTag {
  constructor(t, r, l) { super(t, r, l, 'endstyle'); }
  * render(ctx, emitter) {
    emitter.write('<style>');
    yield this.liquid.renderer.renderTemplates(this.tpls, ctx, emitter);
    emitter.write('</style>');
  }
});
engine.registerTag('section', class extends Tag {
  constructor(token, remain, liquid) { super(token, remain, liquid); this.name = token.args.replace(/['"\s]/g, ''); }
  * render(ctx, emitter) { emitter.write(yield renderSection(this.name, this.name, {}, ctx.getAll())); }
});
engine.registerTag('sections', class extends Tag {
  constructor(token, remain, liquid) { super(token, remain, liquid); this.name = token.args.replace(/['"\s]/g, ''); }
  * render(ctx, emitter) {
    const group = JSON.parse(yield readFile(join(THEME, 'sections', `${this.name}.json`), 'utf8'));
    for (const id of group.order) emitter.write(yield renderSection(id, group.sections[id].type, group.sections[id], ctx.getAll()));
  }
});
void Hash;

/* ---------- Sections ---------- */
function resolveSetting(type, value) {
  if (value == null) return value;
  if (type === 'collection') return data.collections[value] || null;
  if (type === 'blog') return data.blog;
  if (type === 'link_list' || type === 'image_picker') return null;
  return value;
}

async function renderSection(id, type, conf, scope) {
  const file = join(THEME, 'sections', `${type}.liquid`);
  const src = await readFile(file, 'utf8');
  const schema = JSON.parse((src.match(/\{%\s*schema\s*%\}([\s\S]*?)\{%\s*endschema\s*%\}/) || [, '{}'])[1]);
  const settingsOut = {};
  for (const s of schema.settings || []) settingsOut[s.id] = resolveSetting(s.type, conf.settings?.[s.id] ?? s.default);
  const preset = (schema.presets || [])[0];
  let blockConf = conf.blocks ? conf.block_order.map((bid) => conf.blocks[bid]) : preset?.blocks || [];
  const blocks = blockConf.map((b) => {
    const def = (schema.blocks || []).find((x) => x.type === b.type) || { settings: [] };
    const s = {};
    for (const d of def.settings || []) s[d.id] = resolveSetting(d.type, b.settings?.[d.id] ?? d.default);
    return { type: b.type, settings: s, shopify_attributes: '' };
  });
  if (type === 'featured-drop') settingsOut.drop = data.drop;
  if (type === 'hero') settingsOut.image = { src: 'img/hero.svg', alt: 'INNO64 R34 in Midnight Purple' };
  const html = await engine.parseAndRender(src, { ...scope, section: { id, settings: settingsOut, blocks } }, { globals: scope });
  return `<div id="shopify-section-${id}" class="shopify-section">${html}</div>`;
}

/* ---------- Pages ---------- */
// Point Shopify-style URLs at the preview's static files so the pages link together.
function rewriteLinks(html) {
  return html.replace(/href="(\/[^"#?]*)([^"]*)"/g, (all, path, rest) => {
    let m;
    if ((m = path.match(/^\/collections\/([a-z0-9-]+)$/))) return `href="${data.collections[m[1]] ? `collection-${m[1]}.html` : 'collection-1-64-diecast.html'}"`;
    if (path === '/collections') return 'href="collection-1-64-diecast.html"';
    if ((m = path.match(/^\/products\/([a-z0-9-]+)$/))) return `href="product-${m[1]}.html"`;
    if (path === '/pages/drops' || path.startsWith('/pages/drop')) return 'href="drop.html"';
    if (path === '/pages/garage' || path === '/pages/collector-profile' || path.startsWith('/pages/collector')) return 'href="garage.html"';
    if (path === '/pages/brands') return 'href="collection-1-64-diecast.html"';
    if (path === '/cart') return 'href="cart.html"';
    return `href="#"`;
  });
}

const emptyCart = { item_count: 0, items: [], total_price: 0, items_subtotal_price: 0, cart_level_discount_applications: [], currency: { iso_code: 'NZD' } };
const cartWith = (lines) => {
  const items = lines.map(([p, qty, pre], i) => ({
    key: `k${i}`, quantity: qty, url: p.url, image: p.featured_media, vendor: p.vendor, product: p, variant: p.variants[0],
    final_line_price: p.price * qty, url_to_remove: '#', properties: pre ? { _preorder: 'true', 'Expected NZ arrival': 'December 2026' } : {}
  }));
  const total = items.reduce((n, i) => n + i.final_line_price, 0);
  return { ...emptyCart, items, item_count: lines.reduce((n, l) => n + l[1], 0), total_price: total, items_subtotal_price: total };
};
const P = (h) => data.products.find((p) => p.handle === h);

async function page(out, { template, title, pageType, extra = {}, customer = null, cart = emptyCart, templateName, suffix = '' }) {
  const tpl = JSON.parse(await readFile(join(THEME, 'templates', template), 'utf8'));
  const scope = {
    settings,
    shop: { name: 'Scale Culture NZ', url: '', metaobjects: { drop: { values: [data.drop] } } },
    routes: {
      root_url: 'home.html', cart_url: 'cart.html', cart_add_url: 'cart.html', search_url: '#', account_url: 'garage.html', account_login_url: '#',
      account_register_url: '#', account_logout_url: '#', account_addresses_url: '#', collections_url: '#', all_products_collection_url: 'collection.html',
      product_recommendations_url: '#'
    },
    request: { page_type: pageType, locale: { iso_code: 'en' } },
    template: { name: templateName || pageType, suffix },
    canonical_url: '#',
    page_title: title,
    page_description: 'Limited-run die-cast, model kits and automotive collectibles for serious collectors.',
    collections: data.collections,
    blogs: { journal: data.blog },
    customer,
    cart,
    content_for_header: '',
    recommendations: { performed: true, products_count: 4, products: data.products.slice(4, 8) },
    ...extra
  };
  let body = '';
  for (const id of tpl.order) body += await renderSection(id, tpl.sections[id].type, tpl.sections[id], scope);
  const layout = await readFile(join(THEME, 'layout/theme.liquid'), 'utf8');
  let html = await engine.parseAndRender(layout, { ...scope, content_for_layout: body }, { globals: scope });
  html = rewriteLinks(html);
  await writeFile(join(DIST, out), html);
  console.log(`  ✓ ${out}`);
}

await rm(DIST, { recursive: true, force: true });
await mkdir(join(DIST, 'img'), { recursive: true });
await cp(join(THEME, 'assets'), join(DIST, 'assets'), { recursive: true });
for (const [path, svg] of Object.entries(data.IMAGES)) await writeFile(join(DIST, path), svg);
// The hero section falls back to a placeholder without an uploaded image; point it at the sample hero.
data.collections['new-arrivals'].image = null;

const r34 = P('inno64-r34-midnight-purple');
const supra = P('poprace-a80-rocket-bunny');
const kaido = P('kaido-house-510-wagon');

console.log('Rendering preview pages:');
for (const p of data.products) {
  await page(`product-${p.handle}.html`, { template: 'product.json', title: p.title, pageType: 'product', extra: { product: p } });
}
for (const c of Object.values(data.collections)) {
  await page(`collection-${c.handle}.html`, { template: 'collection.json', title: c.title, pageType: 'collection', extra: { collection: c } });
}
await page('home.html', { template: 'index.json', title: 'Scale Culture NZ', pageType: 'index' });
await page('product.html', { template: 'product.json', title: r34.title, pageType: 'product', extra: { product: r34 }, cart: cartWith([[supra, 1, true]]) });
await page('product-preorder.html', { template: 'product.json', title: supra.title, pageType: 'product', extra: { product: supra } });
await page('product-sold-out.html', { template: 'product.json', title: kaido.title, pageType: 'product', extra: { product: kaido } });
await page('collection.html', { template: 'collection.json', title: '1:64 Die-Cast', pageType: 'collection', extra: { collection: data.collections['1-64-diecast'] } });
await page('cart.html', { template: 'cart.json', title: 'Cart', pageType: 'cart', cart: cartWith([[r34, 1], [P('minigt-nsx-type-r-white'), 2], [supra, 1, true]]) });
await page('journal.html', { template: 'blog.json', title: 'Journal', pageType: 'blog', extra: { blog: data.blog } });
await page('article.html', { template: 'article.json', title: data.articles[0].title, pageType: 'article', extra: { blog: data.blog, article: data.articles[0] } });
await page('drop.html', { template: 'metaobject/drop.json', title: 'Japan Drop #005', pageType: 'metaobject', extra: { metaobject: data.drop } });
await page('garage.html', { template: 'page.garage.json', title: 'My Garage', pageType: 'page', suffix: 'garage', customer: data.customer });

// Owner dashboard (collector-service) rendered with sample numbers
const dash = join(here, '..', 'collector-service', 'src', 'dashboard.js');
if (existsSync(dash)) {
  const { buildDashboard, renderDashboard } = await import(dash);
  const now = new Date();
  const orders = [];
  for (let i = 0; i < 140; i++) {
    const p = data.products[(i * 7) % data.products.length];
    const q = 1 + (i % 3 === 0 ? 1 : 0);
    const t = new Date(now.getTime() - (i % 30) * 86400000 - (i % 5) * 3600000);
    orders.push({
      name: `#${1200 + i}`, createdAt: t.toISOString(), total: String(((p.price * q) / 100).toFixed(2)),
      lineItems: [{ productId: String(p.id), vendor: p.vendor, title: p.title, quantity: q, unfulfilledQuantity: i < 6 || p === supra ? q : 0, total: String(((p.price * q) / 100).toFixed(2)), customAttributes: p === supra ? [{ key: '_preorder', value: 'true' }] : [] }]
    });
  }
  const raw = {
    unfulfilledCount: 6,
    orders,
    products: data.products.map((p) => ({
      id: String(p.id), title: p.title, handle: p.handle, vendor: p.vendor, status: 'ACTIVE', totalInventory: p.variants[0].inventory_quantity, tracksInventory: true,
      availability: p.metafields.scale.availability.value, wishlistCount: p.metafields.scale.wishlist_count.value, scale: p.metafields.scale.scale.value, make: p.metafields.scale.vehicle_make.value
    })),
    drops: [
      { handle: 'japan-drop-004', name: 'Japan Drop #004', release: new Date(now.getTime() - 18 * 86400000).toISOString(), productIds: data.products.slice(0, 6).map((p) => String(p.id)) },
      { handle: 'japan-drop-003', name: 'Japan Drop #003', release: new Date(now.getTime() - 45 * 86400000).toISOString(), productIds: data.products.slice(4).map((p) => String(p.id)) }
    ]
  };
  await writeFile(join(DIST, 'dashboard.html'), renderDashboard(buildDashboard(raw, { now }), { shop: 'scaleculture.myshopify.com' }));
  console.log('  ✓ dashboard.html');
}
