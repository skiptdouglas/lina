import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  upsertGarage, applyOrderStatus, garageStats, sanitizeProfile, mergeWishlist, publicProfile, snapshotFromProduct, handleize
} from '../src/collector.js';

const product = (id, make, model, gen, extra = {}) => ({
  id, handle: `p-${id}`, title: `P ${id}`, vendor: 'INNO64', image: '',
  metafields: { vehicle_make: make, vehicle_model: model, vehicle_generation: gen, scale: '1:64', ...extra }
});
const snap = (...a) => snapshotFromProduct(product(...a));

test('snapshot groups by make/model/generation', () => {
  const s = snap(1, 'Nissan', 'Skyline', 'R34', { card_title: 'Nissan Skyline GT-R R34' });
  assert.equal(s.pid, '1');
  assert.equal(s.group, 'Nissan Skyline R34');
  assert.equal(s.card_title, 'Nissan Skyline GT-R R34');
  assert.equal(snap(2, null, null, null).make, 'Other');
});

test('upsertGarage adds, updates status, keeps added date, removes', () => {
  const t0 = new Date('2026-01-01T00:00:00Z');
  const t1 = new Date('2026-02-01T00:00:00Z');
  let g = upsertGarage([], snap(1, 'Nissan', 'Skyline', 'R34'), 'wanted', { now: t0 });
  assert.equal(g.length, 1);
  g = upsertGarage(g, snap(1, 'Nissan', 'Skyline', 'R34'), 'owned', { now: t1, note: 'Bayside Blue' });
  assert.equal(g.length, 1);
  assert.equal(g[0].status, 'owned');
  assert.equal(g[0].added, t0.toISOString());
  assert.equal(g[0].note, 'Bayside Blue');
  g = upsertGarage(g, { pid: '1' }, null);
  assert.equal(g.length, 0);
  assert.throws(() => upsertGarage([], snap(1, 'Nissan'), 'stolen'), /status must be/);
});

test('applyOrderStatus only upgrades', () => {
  let g = upsertGarage([], snap(1, 'Nissan', 'Skyline', 'R34'), 'owned');
  assert.equal(applyOrderStatus(g, snap(1, 'Nissan', 'Skyline', 'R34'), 'preordered')[0].status, 'owned');
  g = upsertGarage([], snap(2, 'Toyota', 'Supra', 'A80'), 'wanted');
  assert.equal(applyOrderStatus(g, snap(2, 'Toyota', 'Supra', 'A80'), 'preordered')[0].status, 'preordered');
  assert.equal(applyOrderStatus([], snap(3, 'Mazda'), 'owned')[0].status, 'owned');
});

test('garageStats: top 4 makes + Other, collections, top scale', () => {
  let g = [];
  let id = 0;
  const add = (make, n, status = 'owned', model = 'X', gen = '') => {
    for (let i = 0; i < n; i++) g = upsertGarage(g, snap(++id, make, model, gen), status);
  };
  add('Nissan', 21, 'owned', 'Skyline', 'R34');
  add('Porsche', 17);
  add('Toyota', 12);
  add('BMW', 8);
  add('Honda', 5);
  add('Mazda', 3);
  add('Other', 18);
  add('Nissan', 2, 'wanted', 'Skyline', 'R34');
  const s = garageStats(g);
  assert.equal(s.owned, 84);
  assert.equal(s.wanted, 2);
  assert.deepEqual(s.makes, [
    { make: 'Nissan', count: 21 }, { make: 'Porsche', count: 17 }, { make: 'Toyota', count: 12 },
    { make: 'BMW', count: 8 }, { make: 'Other', count: 26 }
  ]);
  assert.equal(s.collections[0].group, 'Nissan Skyline R34');
  assert.equal(s.collections[0].count, 23);
  assert.deepEqual(s.top_make_handles, ['nissan', 'porsche', 'toyota', 'bmw']);
  assert.equal(s.top_scale, '1:64');
});

test('sanitizeProfile trims, caps, requires a name to go public, keeps slug', () => {
  const p = sanitizeProfile({ display_name: '  R34 Hunter  ', bio: 'x'.repeat(500), interests: { makes: ['Nissan', 'Nissan', 5, ''] }, public: true }, { slug: 'r34-hunter' });
  assert.equal(p.display_name, 'R34 Hunter');
  assert.equal(p.bio.length, 280);
  assert.deepEqual(p.interests.makes, ['Nissan']);
  assert.equal(p.slug, 'r34-hunter');
  assert.equal(p.auto_garage, true);
  assert.throws(() => sanitizeProfile({ public: true, display_name: '' }), /display name/);
  assert.throws(() => sanitizeProfile(null), /object/);
});

test('mergeWishlist de-dupes and rejects junk handles', () => {
  assert.deepEqual(mergeWishlist(['a', 'b'], ['b', 'c', 'BAD HANDLE', 7]), ['a', 'b', 'c']);
});

test('publicProfile hides notes, private statuses and identifiers', () => {
  let g = upsertGarage([], snap(1, 'Nissan', 'Skyline', 'R34'), 'owned', { note: 'paid $400' });
  g = upsertGarage(g, snap(2, 'Toyota', 'Supra', 'A80'), 'wanted');
  g = upsertGarage(g, snap(3, 'Mazda', 'RX-7', 'FD3S'), 'preordered');
  const pub = publicProfile({ display_name: 'A', show_wanted: false }, g);
  assert.equal(pub.garage.length, 1);
  assert.equal(pub.garage[0].note, undefined);
  assert.equal(pub.garage[0].pid, undefined);
  assert.equal(publicProfile({ display_name: 'A', show_wanted: true }, g).garage.length, 2);
});

test('handleize', () => {
  assert.equal(handleize('Mine’s R34 Fan!'), 'mine-s-r34-fan');
  assert.equal(handleize('1:64 Café'), '1-64-cafe');
});

import { applyLimitedPurchases, nzToday } from '../src/collector.js';

test('applyLimitedPurchases counts limited lines once per order, reverses on cancel, prunes expired', () => {
  const byId = new Map([
    ['1', { metafields: { max_per_customer: 2, limit_until: '2026-10-20' } }],
    ['2', { metafields: {} }],
    ['3', { metafields: { max_per_customer: 1, limit_until: '2026-10-01' } }]
  ]);
  const order = { id: 501, line_items: [{ product_id: 1, quantity: 1 }, { product_id: 2, quantity: 5 }, { product_id: 3, quantity: 1 }] };
  let r = applyLimitedPurchases({ 9: { qty: 1, until: '2026-09-01' } }, order, byId, { today: '2026-10-18' });
  assert.equal(r.changed, true);
  assert.deepEqual(r.history[1], { qty: 1, until: '2026-10-20' });
  assert.equal(r.history[2], undefined); // unlimited
  assert.equal(r.history[3], undefined); // limit window over
  assert.equal(r.history[9], undefined); // expired entry pruned
  // Retried webhook: no double count
  const again = applyLimitedPurchases(r.history, order, byId, { today: '2026-10-18' });
  assert.equal(again.changed, false);
  assert.equal(again.history[1].qty, 1);
  // Cancellation gives the allowance back
  r = applyLimitedPurchases(r.history, order, byId, { today: '2026-10-18', cancelled: true });
  assert.equal(r.history[1].qty, 0);
  assert.equal(applyLimitedPurchases(r.history, order, byId, { today: '2026-10-18', cancelled: true }).changed, false);
});

test('nzToday uses Auckland time', () => {
  assert.equal(nzToday(new Date('2026-10-19T12:30:00Z')), '2026-10-20');
});
