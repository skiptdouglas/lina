// Owner dashboard (SOP §34, §35): one page with today's sales, fulfilment queue,
// low stock, incoming stock, pre-orders, best sellers, revenue by brand / make /
// scale, wishlist demand on sold-out models and sell-through per drop.
//
// buildDashboard() is pure (tested); fetchDashboardData() talks to the Admin API;
// renderDashboard() returns a self-contained HTML page.

const TZ = 'Pacific/Auckland';
const DAY = 86400000;

const nzDate = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(d));
const num = (v) => Number.parseFloat(v || 0) || 0;

function topN(map, n, otherLabel = 'Other') {
  const sorted = [...map.entries()].sort((a, b) => b[1].revenue - a[1].revenue);
  const top = sorted.slice(0, n).map(([label, v]) => ({ label, ...v }));
  const rest = sorted.slice(n);
  if (rest.length) {
    top.push(rest.reduce((acc, [, v]) => ({ label: otherLabel, revenue: acc.revenue + v.revenue, units: acc.units + v.units }), { label: otherLabel, revenue: 0, units: 0 }));
  }
  return top;
}

const isPreorderLine = (li) => (li.customAttributes || []).some((a) => a.key === '_preorder' && String(a.value) === 'true');

/**
 * @param raw {orders, products, drops, unfulfilledCount}
 *   orders:   [{name, createdAt, cancelledAt, total, lineItems:[{productId, vendor, title, quantity, unfulfilledQuantity, total, customAttributes}]}]
 *   products: [{id, title, handle, vendor, totalInventory, tracksInventory, status, availability, wishlistCount, scale, make}]
 *   drops:    [{handle, name, release, productIds:[]}]
 */
export function buildDashboard(raw, { now = new Date(), lowStockThreshold = 3, orderWindowDays = 60 } = {}) {
  const orders = (raw.orders || []).filter((o) => !o.cancelledAt);
  const products = raw.products || [];
  const byId = new Map(products.map((p) => [String(p.id), p]));
  const today = nzDate(now);
  const since = (days) => now.getTime() - days * DAY;

  // Sales tiles
  const todays = orders.filter((o) => nzDate(o.createdAt) === today);
  const last7 = orders.filter((o) => new Date(o.createdAt).getTime() >= since(7));
  const last30 = orders.filter((o) => new Date(o.createdAt).getTime() >= since(30));
  const sum = (list) => list.reduce((n, o) => n + num(o.total), 0);
  const revenue30 = sum(last30);

  // Daily revenue, last 30 NZ days (oldest → newest)
  const daily = [];
  for (let i = 29; i >= 0; i--) {
    const day = nzDate(now.getTime() - i * DAY);
    daily.push({ day, revenue: 0, orders: 0 });
  }
  const dayIndex = new Map(daily.map((d, i) => [d.day, i]));
  for (const o of last30) {
    const i = dayIndex.get(nzDate(o.createdAt));
    if (i !== undefined) {
      daily[i].revenue += num(o.total);
      daily[i].orders += 1;
    }
  }

  // Line-level aggregates over 30 days
  const byProduct = new Map();
  const byBrand = new Map();
  const byMake = new Map();
  const byScale = new Map();
  const bump = (map, key, revenue, units) => {
    const v = map.get(key) || { revenue: 0, units: 0 };
    v.revenue += revenue;
    v.units += units;
    map.set(key, v);
  };
  for (const o of last30) {
    for (const li of o.lineItems || []) {
      const p = byId.get(String(li.productId));
      const rev = num(li.total);
      bump(byProduct, String(li.productId || li.title), rev, li.quantity);
      bump(byBrand, li.vendor || p?.vendor || 'Unknown', rev, li.quantity);
      bump(byMake, p?.make || 'Unknown', rev, li.quantity);
      bump(byScale, p?.scale || 'Unknown', rev, li.quantity);
    }
  }
  const bestSellers = [...byProduct.entries()]
    .map(([id, v]) => ({ id, title: byId.get(id)?.title || id, handle: byId.get(id)?.handle, ...v }))
    .sort((a, b) => b.units - a.units || b.revenue - a.revenue)
    .slice(0, 10);

  // Open pre-orders (all orders in window with unfulfilled pre-order lines)
  const preorders = new Map();
  for (const o of orders) {
    for (const li of o.lineItems || []) {
      if (!isPreorderLine(li) || !(li.unfulfilledQuantity > 0)) continue;
      const key = String(li.productId || li.title);
      const v = preorders.get(key) || { title: byId.get(key)?.title || li.title, units: 0, orders: 0 };
      v.units += li.unfulfilledQuantity;
      v.orders += 1;
      preorders.set(key, v);
    }
  }
  const preorderList = [...preorders.values()].sort((a, b) => b.units - a.units);

  // Stock
  const live = products.filter((p) => p.status === 'ACTIVE');
  const auto = (p) => !p.availability || p.availability === 'auto';
  const lowStock = live
    .filter((p) => auto(p) && p.tracksInventory && p.totalInventory > 0 && p.totalInventory <= lowStockThreshold)
    .sort((a, b) => a.totalInventory - b.totalInventory);
  const incoming = live.filter((p) => p.availability === 'coming_soon' || p.availability === 'incoming');
  const demand = live
    .filter((p) => p.availability !== 'discontinued' && p.totalInventory <= 0 && p.wishlistCount > 0)
    .sort((a, b) => b.wishlistCount - a.wishlistCount)
    .slice(0, 10);

  // Sell-through per drop: units sold in the 7 days after release ÷ units available at release
  // (sold since release + on hand now). Only drops whose release falls inside the order window.
  const windowStart = now.getTime() - orderWindowDays * DAY;
  const drops = (raw.drops || [])
    .filter((d) => d.release && new Date(d.release).getTime() <= now.getTime())
    .sort((a, b) => new Date(b.release) - new Date(a.release))
    .slice(0, 6)
    .map((d) => {
      const ids = new Set(d.productIds.map(String));
      const start = new Date(d.release).getTime();
      let sold7 = 0;
      let soldSince = 0;
      for (const o of orders) {
        const t = new Date(o.createdAt).getTime();
        if (t < start) continue;
        for (const li of o.lineItems || []) {
          if (!ids.has(String(li.productId))) continue;
          soldSince += li.quantity;
          if (t < start + 7 * DAY) sold7 += li.quantity;
        }
      }
      const onHand = [...ids].reduce((n, id) => n + Math.max(0, byId.get(id)?.totalInventory || 0), 0);
      const units = soldSince + onHand;
      return {
        name: d.name,
        handle: d.handle,
        release: d.release,
        skus: ids.size,
        units,
        sold7,
        sellThrough: units ? sold7 / units : 0,
        complete: start >= windowStart && now.getTime() - start >= 7 * DAY
      };
    });

  return {
    generatedAt: now.toISOString(),
    tiles: {
      todaySales: sum(todays),
      todayOrders: todays.length,
      sales7: sum(last7),
      sales30: revenue30,
      aov30: last30.length ? revenue30 / last30.length : 0,
      awaitingFulfilment: raw.unfulfilledCount ?? null,
      openPreorderUnits: preorderList.reduce((n, p) => n + p.units, 0),
      incoming: incoming.length,
      lowStock: lowStock.length
    },
    daily,
    bestSellers,
    brands: topN(byBrand, 8),
    makes: topN(byMake, 8),
    scales: topN(byScale, 6),
    lowStock: lowStock.slice(0, 15).map(({ title, handle, totalInventory }) => ({ title, handle, totalInventory })),
    incoming: incoming.slice(0, 15).map(({ title, handle, availability }) => ({ title, handle, availability })),
    preorders: preorderList.slice(0, 15),
    demand: demand.map(({ title, handle, wishlistCount }) => ({ title, handle, wishlistCount })),
    drops
  };
}

export async function fetchDashboardData(admin, { now = new Date(), days = 60, maxProducts = 2000 } = {}) {
  const sinceDate = new Date(now.getTime() - days * DAY).toISOString().slice(0, 10);
  const orders = [];
  let after = null;
  do {
    const data = await admin.gql(
      `query($q: String!, $after: String) {
        orders(first: 100, after: $after, query: $q, sortKey: CREATED_AT, reverse: true) {
          pageInfo { hasNextPage endCursor }
          nodes {
            name createdAt cancelledAt
            currentTotalPriceSet { shopMoney { amount } }
            lineItems(first: 50) { nodes {
              title vendor quantity unfulfilledQuantity
              product { legacyResourceId }
              originalTotalSet { shopMoney { amount } }
              customAttributes { key value }
            } }
          }
        }
      }`,
      { q: `created_at:>=${sinceDate}`, after }
    );
    for (const o of data.orders.nodes) {
      orders.push({
        name: o.name,
        createdAt: o.createdAt,
        cancelledAt: o.cancelledAt,
        total: o.currentTotalPriceSet.shopMoney.amount,
        lineItems: o.lineItems.nodes.map((li) => ({
          productId: li.product?.legacyResourceId,
          title: li.title,
          vendor: li.vendor,
          quantity: li.quantity,
          unfulfilledQuantity: li.unfulfilledQuantity,
          total: li.originalTotalSet.shopMoney.amount,
          customAttributes: li.customAttributes
        }))
      });
    }
    after = data.orders.pageInfo.hasNextPage ? data.orders.pageInfo.endCursor : null;
  } while (after && orders.length < 5000);

  const products = [];
  after = null;
  do {
    const data = await admin.gql(
      `query($after: String) {
        products(first: 100, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            legacyResourceId title handle vendor status totalInventory tracksInventory
            availability: metafield(namespace: "scale", key: "availability") { value }
            wishlist: metafield(namespace: "scale", key: "wishlist_count") { value }
            scale: metafield(namespace: "scale", key: "scale") { value }
            make: metafield(namespace: "scale", key: "vehicle_make") { value }
          }
        }
      }`,
      { after }
    );
    for (const p of data.products.nodes) {
      products.push({
        id: p.legacyResourceId,
        title: p.title,
        handle: p.handle,
        vendor: p.vendor,
        status: p.status,
        totalInventory: p.totalInventory,
        tracksInventory: p.tracksInventory,
        availability: p.availability?.value || 'auto',
        wishlistCount: parseInt(p.wishlist?.value || '0', 10) || 0,
        scale: p.scale?.value || '',
        make: p.make?.value || ''
      });
    }
    after = data.products.pageInfo.hasNextPage ? data.products.pageInfo.endCursor : null;
  } while (after && products.length < maxProducts);

  const dropData = await admin.gql(`{
    metaobjects(type: "drop", first: 50) { nodes {
      handle
      name: field(key: "name") { value }
      release: field(key: "release_date") { value }
      collection: field(key: "collection") { reference { ... on Collection { products(first: 250) { nodes { legacyResourceId } } } } }
    } }
  }`);
  const drops = dropData.metaobjects.nodes.map((d) => ({
    handle: d.handle,
    name: d.name?.value || d.handle,
    release: d.release?.value,
    productIds: d.collection?.reference?.products.nodes.map((p) => p.legacyResourceId) || []
  }));

  let unfulfilledCount = null;
  try {
    const c = await admin.gql(`{ ordersCount(query: "fulfillment_status:unfulfilled OR fulfillment_status:partial status:open") { count } }`);
    unfulfilledCount = c.ordersCount.count;
  } catch {
    unfulfilledCount = orders.filter((o) => !o.cancelledAt && o.lineItems.some((li) => li.unfulfilledQuantity > 0)).length;
  }

  return { orders, products, drops, unfulfilledCount };
}

/* ---------- HTML ---------- */

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const money = (v) => new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD', maximumFractionDigits: v >= 1000 ? 0 : 2 }).format(v);
const pct = (v) => `${Math.round(v * 100)}%`;

function barList(rows, { value, label, format, tip }) {
  if (!rows.length) return '<p class="muted">No sales in the last 30 days.</p>';
  const max = Math.max(...rows.map(value), 1);
  return `<table class="bars"><tbody>${rows
    .map(
      (r) => `<tr data-tip="${esc(tip(r))}" tabindex="0">
        <th scope="row">${esc(label(r))}</th>
        <td class="bars__track"><span class="bars__bar" style="width:${Math.max(1, (value(r) / max) * 100).toFixed(1)}%"></span></td>
        <td class="num">${esc(format(r))}</td></tr>`
    )
    .join('')}</tbody></table>`;
}

function list(rows, cols, empty) {
  if (!rows.length) return `<p class="muted">${esc(empty)}</p>`;
  return `<div class="scroll"><table class="list"><thead><tr>${cols.map((c) => `<th${c.num ? ' class="num"' : ''}>${esc(c.h)}</th>`).join('')}</tr></thead><tbody>${rows
    .map((r) => `<tr>${cols.map((c) => `<td${c.num ? ' class="num"' : ''}>${c.html ? c.v(r) : esc(c.v(r))}</td>`).join('')}</tr>`)
    .join('')}</tbody></table></div>`;
}

export function renderDashboard(d, { shop, lowStockThreshold = 3 }) {
  const t = d.tiles;
  const productLink = (r) => (r.handle ? `<a href="https://${esc(shop)}/products/${esc(r.handle)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title));
  const maxDay = Math.max(...d.daily.map((x) => x.revenue), 1);
  const peak = d.daily.reduce((a, b) => (b.revenue > a.revenue ? b : a), d.daily[0]);
  const tile = (label, value, note = '', flag = '') =>
    `<div class="tile${flag ? ` tile--${flag}` : ''}"><span class="tile__label">${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<span class="tile__note">${note}</span>` : ''}</div>`;

  return `<!doctype html>
<html lang="en-NZ"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Owner Dashboard</title>
<meta http-equiv="refresh" content="300">
<style>
:root{--bg:#f4f4f2;--surface:#fcfcfb;--ink:#0b0b0c;--ink-2:#4a4c50;--muted:#8a8d91;--grid:#e3e4e2;--accent:#d7262e;--warn:#9a5b00;--warn-bg:#fff4e0;--good:#1f7a45}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b0b0c;--surface:#161719;--ink:#f2f2f0;--ink-2:#b9bbbe;--muted:#8a8d91;--grid:#2a2c2f;--accent:#ef4a50;--warn:#f0b54a;--warn-bg:#2b2111;--good:#5cc98a}}
:root[data-theme="dark"]{--bg:#0b0b0c;--surface:#161719;--ink:#f2f2f0;--ink-2:#b9bbbe;--muted:#8a8d91;--grid:#2a2c2f;--accent:#ef4a50;--warn:#f0b54a;--warn-bg:#2b2111;--good:#5cc98a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,Helvetica,Arial,sans-serif}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px;padding:20px 16px 8px;max-width:1280px;margin:0 auto}
h1{margin:0;font:800 28px/1 "Barlow Condensed","Arial Narrow",sans-serif;text-transform:uppercase;letter-spacing:.04em}h1 span{color:var(--accent)}
h2{margin:0 0 12px;font:700 16px/1.2 "Barlow Condensed","Arial Narrow",sans-serif;text-transform:uppercase;letter-spacing:.08em}
.muted,.sub{color:var(--muted)}main{max-width:1280px;margin:0 auto;padding:8px 16px 48px;display:grid;gap:16px}
.tiles{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}@media(min-width:800px){.tiles{grid-template-columns:repeat(4,1fr)}}
.tile{background:var(--surface);border-radius:8px;padding:16px;display:grid;gap:4px}.tile strong{font:700 28px/1.1 Inter,sans-serif;font-variant-numeric:tabular-nums}
.tile__label{font-size:12px;font-weight:600;color:var(--ink-2);text-transform:uppercase;letter-spacing:.06em}.tile__note{font-size:12px;color:var(--muted)}
.tile--warn{box-shadow:inset 4px 0 0 var(--warn)}
.grid{display:grid;gap:16px}@media(min-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.grid--3{grid-template-columns:repeat(3,minmax(0,1fr))}}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.scroll table{min-width:420px}.card{background:var(--surface);border-radius:8px;padding:16px;min-width:0}
.cols{display:flex;align-items:flex-end;gap:2px;height:140px;border-bottom:1px solid var(--grid);position:relative}
.cols span{flex:1;background:var(--accent);border-radius:4px 4px 0 0;min-height:1px;max-width:24px;margin:0 auto;position:relative}
.cols span:hover,.cols span:focus{opacity:.75;outline:none}
.axis{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:4px}
.chart-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px}.peak{font-size:12px;color:var(--ink-2)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.bars th{font-weight:500;text-align:left;padding:5px 10px 5px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}
.bars__track{width:100%;padding:5px 0}.bars__bar{display:block;height:12px;background:var(--accent);border-radius:0 4px 4px 0}
.bars tr:hover .bars__bar,.bars tr:focus .bars__bar{opacity:.75}.bars tr:focus{outline:none}
.num{text-align:right;padding-left:10px;white-space:nowrap}
.list th.num{text-align:right}.list th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600;padding:0 0 6px;border-bottom:1px solid var(--grid)}
.list th{text-align:left}.list th.num{text-align:right}.list td{padding:7px 0;border-bottom:1px solid var(--grid)}.list td+td,.list th+th{padding-left:10px}
a{color:inherit;text-decoration-color:var(--muted)}
.status{display:inline-flex;gap:4px;align-items:center;font-size:12px;font-weight:600;color:var(--warn);background:var(--warn-bg);padding:2px 8px;border-radius:999px}
.note{font-size:12px;color:var(--muted);margin:10px 0 0}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);font-size:12px;padding:6px 8px;border-radius:4px;opacity:0;transition:opacity .1s;z-index:9;max-width:260px}
</style></head><body>
<header><h1>Scale Culture<span>.</span> Owner</h1><span class="sub">Updated ${esc(new Date(d.generatedAt).toLocaleString('en-NZ', { timeZone: TZ }))} · refreshes every 5 min</span></header>
<main>
<section class="tiles" aria-label="Key numbers">
${tile("Today's sales", money(t.todaySales), `${t.todayOrders} order${t.todayOrders === 1 ? '' : 's'}`)}
${tile('Awaiting fulfilment', t.awaitingFulfilment ?? '—', 'open orders', t.awaitingFulfilment > 0 ? 'warn' : '')}
${tile('Open pre-orders', `${t.openPreorderUnits} units`, `${d.preorders.length} models`)}
${tile('Low stock', t.lowStock, `≤ ${lowStockThreshold} left · ${t.incoming} incoming`, t.lowStock > 0 ? 'warn' : '')}
${tile('Last 7 days', money(t.sales7))}
${tile('Last 30 days', money(t.sales30))}
${tile('Avg order (30d)', money(t.aov30))}
${tile('Incoming models', t.incoming, 'coming soon + incoming')}
</section>

<section class="card" aria-labelledby="h-daily">
<div class="chart-head"><h2 id="h-daily">Revenue per day — last 30 days</h2><span class="peak">Peak ${esc(money(peak.revenue))} · ${esc(peak.day.slice(5))}</span></div>
<div class="cols" role="img" aria-label="Daily revenue, peak ${esc(money(peak.revenue))} on ${esc(peak.day)}">
${d.daily.map((x) => `<span tabindex="0" style="height:${((x.revenue / maxDay) * 100).toFixed(1)}%" data-tip="${esc(`${x.day}: ${money(x.revenue)} · ${x.orders} orders`)}"></span>`).join('')}
</div>
<div class="axis"><span>${esc(d.daily[0].day.slice(5))}</span><span>${esc(d.daily.at(-1).day.slice(5))}</span></div>
<details><summary class="note">Table view</summary>${list(d.daily, [{ h: 'Day', v: (r) => r.day }, { h: 'Orders', v: (r) => r.orders, num: true }, { h: 'Revenue', v: (r) => money(r.revenue), num: true }], '')}</details>
</section>

<div class="grid">
<section class="card"><h2>Best-selling models — 30 days</h2>
${barList(d.bestSellers, { value: (r) => r.units, label: (r) => r.title, format: (r) => `${r.units} sold`, tip: (r) => `${r.title}: ${r.units} units · ${money(r.revenue)}` })}</section>
<section class="card"><h2>Revenue by brand — 30 days</h2>
${barList(d.brands, { value: (r) => r.revenue, label: (r) => r.label, format: (r) => money(r.revenue), tip: (r) => `${r.label}: ${money(r.revenue)} · ${r.units} units` })}</section>
<section class="card"><h2>Revenue by vehicle manufacturer</h2>
${barList(d.makes, { value: (r) => r.revenue, label: (r) => r.label, format: (r) => money(r.revenue), tip: (r) => `${r.label}: ${money(r.revenue)} · ${r.units} units` })}</section>
<section class="card"><h2>Revenue by scale</h2>
${barList(d.scales, { value: (r) => r.revenue, label: (r) => r.label, format: (r) => money(r.revenue), tip: (r) => `${r.label}: ${money(r.revenue)} · ${r.units} units` })}</section>
</div>

<section class="card"><h2>Sell-through per drop</h2>
${list(d.drops, [
  { h: 'Drop', v: (r) => r.name },
  { h: 'Released', v: (r) => new Date(r.release).toLocaleDateString('en-NZ', { timeZone: TZ, day: 'numeric', month: 'short' }) },
  { h: 'SKUs', v: (r) => r.skus, num: true },
  { h: 'Units', v: (r) => r.units, num: true },
  { h: 'Sold in 7 days', v: (r) => r.sold7, num: true },
  { h: 'Sell-through', v: (r) => (r.complete ? pct(r.sellThrough) : `${pct(r.sellThrough)} so far`), num: true }
], 'No drops released yet.')}
<p class="note">Units = sold since release + on hand now. Drops older than the 60-day order window show partial figures.</p></section>

<div class="grid grid--3">
<section class="card"><h2>Low stock</h2>
${list(d.lowStock, [{ h: 'Model', v: productLink, html: true }, { h: 'Left', v: (r) => `<span class="status">⚠ ${r.totalInventory}</span>`, html: true, num: true }], 'Nothing running low.')}</section>
<section class="card"><h2>Sold out, wanted</h2>
${list(d.demand, [{ h: 'Model', v: productLink, html: true }, { h: 'Wishlists', v: (r) => r.wishlistCount, num: true }], 'No wishlist demand on sold-out models yet.')}
<p class="note">Reorder candidates: sold-out models collectors still want.</p></section>
<section class="card"><h2>Open pre-orders</h2>
${list(d.preorders, [{ h: 'Model', v: (r) => r.title }, { h: 'Orders', v: (r) => r.orders, num: true }, { h: 'Units', v: (r) => r.units, num: true }], 'No open pre-orders.')}</section>
</div>

<section class="card"><h2>Incoming stock</h2>
${list(d.incoming, [{ h: 'Model', v: productLink, html: true }, { h: 'Stage', v: (r) => (r.availability === 'incoming' ? 'Shipped from Japan' : 'Ordered from supplier') }], 'Nothing on order.')}
<p class="note">Product views vs sales (high views, low sales) live in Shopify → Analytics → Reports → “Product views and conversion”.</p></section>
</main>
<div id="tip" role="tooltip"></div>
<script>
const tip=document.getElementById('tip');
const show=(el,x,y)=>{tip.textContent=el.dataset.tip;tip.style.left=Math.min(x+12,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(y-36)+'px';tip.style.opacity=1};
document.addEventListener('pointermove',e=>{const el=e.target.closest('[data-tip]');el?show(el,e.clientX,e.clientY):tip.style.opacity=0});
document.addEventListener('focusin',e=>{const el=e.target.closest('[data-tip]');if(el){const r=el.getBoundingClientRect();show(el,r.left,r.top)}});
document.addEventListener('focusout',()=>tip.style.opacity=0);
</script>
</body></html>`;
}
