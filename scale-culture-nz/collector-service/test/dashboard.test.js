import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildDashboard, renderDashboard } from '../src/dashboard.js';

const now = new Date('2026-10-20T03:00:00Z'); // 4pm 20 Oct in Auckland (NZDT)
const iso = (s) => new Date(s).toISOString();
const product = (id, extra) => ({ id, title: `Model ${id}`, handle: `m-${id}`, vendor: 'INNO64', status: 'ACTIVE', totalInventory: 10, tracksInventory: true, availability: 'auto', wishlistCount: 0, scale: '1:64', make: 'Nissan', ...extra });
const line = (productId, quantity, total, extra = {}) => ({ productId, vendor: 'INNO64', title: `Model ${productId}`, quantity, unfulfilledQuantity: 0, total, customAttributes: [], ...extra });

const raw = {
  unfulfilledCount: 3,
  products: [
    product('1'),
    product('2', { vendor: 'POP RACE', make: 'Toyota', totalInventory: 2 }),
    product('3', { totalInventory: 0, wishlistCount: 32 }),
    product('4', { availability: 'incoming', totalInventory: 0 }),
    product('5', { availability: 'preorder', totalInventory: 20, scale: '1:18' }),
    product('6', { availability: 'discontinued', totalInventory: 0, wishlistCount: 99 })
  ],
  orders: [
    // Today in NZ (19 Oct 23:30 UTC = 20 Oct 12:30 NZDT)
    { name: '#1001', createdAt: iso('2026-10-19T23:30:00Z'), total: '99.90', lineItems: [line('1', 2, '99.90')] },
    { name: '#1002', createdAt: iso('2026-10-18T02:00:00Z'), total: '54.95', lineItems: [line('5', 1, '54.95', { unfulfilledQuantity: 1, customAttributes: [{ key: '_preorder', value: 'true' }] })] },
    { name: '#1003', createdAt: iso('2026-10-11T01:00:00Z'), total: '200', lineItems: [line('2', 4, '200', { vendor: 'POP RACE' })] },
    { name: '#1004', createdAt: iso('2026-10-12T01:00:00Z'), cancelledAt: iso('2026-10-12T02:00:00Z'), total: '500', lineItems: [line('1', 10, '500')] }
  ],
  drops: [{ handle: 'japan-drop-004', name: 'Japan Drop #004', release: iso('2026-10-10T06:00:00Z'), productIds: ['1', '2'] }]
};

test('tiles use NZ day boundaries and ignore cancelled orders', () => {
  const d = buildDashboard(raw, { now });
  assert.equal(d.tiles.todayOrders, 1);
  assert.equal(d.tiles.todaySales, 99.9);
  assert.equal(d.tiles.sales30, 354.85);
  assert.equal(d.tiles.awaitingFulfilment, 3);
  assert.equal(d.tiles.openPreorderUnits, 1);
  assert.equal(d.daily.length, 30);
  assert.equal(d.daily.at(-1).revenue, 99.9);
});

test('stock lists: low stock, incoming, sold-out demand excludes discontinued', () => {
  const d = buildDashboard(raw, { now, lowStockThreshold: 3 });
  assert.deepEqual(d.lowStock.map((p) => p.handle), ['m-2']);
  assert.deepEqual(d.incoming.map((p) => p.handle), ['m-4']);
  assert.deepEqual(d.demand.map((p) => [p.handle, p.wishlistCount]), [['m-3', 32]]);
});

test('revenue by brand / make / scale and best sellers', () => {
  const d = buildDashboard(raw, { now });
  assert.equal(d.bestSellers[0].id, '2');
  assert.deepEqual(d.brands.map((b) => b.label), ['POP RACE', 'INNO64']);
  assert.deepEqual(d.makes.map((b) => b.label), ['Toyota', 'Nissan']);
  assert.equal(d.scales.find((s) => s.label === '1:18').revenue, 54.95);
});

test('drop sell-through = sold in 7 days ÷ (sold since release + on hand)', () => {
  const [drop] = buildDashboard(raw, { now }).drops;
  // sold since release: 2 (#1001) + 4 (#1003) = 6; on hand 10 + 2 = 12 → 18 units; 4 sold in first 7 days
  assert.equal(drop.units, 18);
  assert.equal(drop.sold7, 4);
  assert.equal(Math.round(drop.sellThrough * 100), 22);
  assert.equal(drop.complete, true);
});

test('renders escaped HTML', () => {
  const d = buildDashboard({ ...raw, products: [product('1', { title: '<script>x</script>', totalInventory: 1 })] }, { now });
  const html = renderDashboard(d, { shop: 'scaleculture.myshopify.com' });
  assert.ok(html.includes('&lt;script&gt;x&lt;/script&gt;'));
  assert.ok(!html.includes('<script>x</script>'));
  assert.ok(html.includes("Today&#39;s sales") || html.includes("Today's sales"));
});
