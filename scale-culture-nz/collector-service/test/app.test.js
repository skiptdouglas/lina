import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { Readable } from 'node:stream';
import { createApp } from '../src/app.js';
import { verifyProxySignature, verifyOAuthHmac } from '../src/shopify.js';

const SECRET = 'shhh';
const config = { shop: 'scaleculture.myshopify.com', apiKey: 'key', apiSecret: SECRET, serviceUrl: 'https://svc.test' };

function signProxy(params) {
  const msg = Object.entries(params).map(([k, v]) => `${k}=${v}`).sort().join('');
  return createHmac('sha256', SECRET).update(msg).digest('hex');
}

function proxyUrl(path, { customer = '42', ts = Math.floor(Date.now() / 1000) } = {}) {
  const params = { shop: config.shop, path_prefix: '/apps/collector', timestamp: String(ts), logged_in_customer_id: customer };
  return `${path}?${new URLSearchParams({ ...params, signature: signProxy(params) })}`;
}

function fakeAdmin() {
  const db = { customers: { 42: { email: 'c@test.nz', data: {} } }, counts: {}, collectors: {} };
  const products = {
    1: { id: '1', handle: 'inno64-r34', title: 'INNO64 – R34', vendor: 'INNO64', image: '', metafields: { vehicle_make: 'Nissan', vehicle_model: 'Skyline', vehicle_generation: 'R34', scale: '1:64' } },
    2: { id: '2', handle: 'pop-a80', title: 'POP – A80', vendor: 'POP RACE', image: '', metafields: { vehicle_make: 'Toyota', vehicle_model: 'Supra', vehicle_generation: 'A80', scale: '1:64' } }
  };
  return {
    db,
    async getCustomer(id) {
      const c = db.customers[id];
      return c ? { email: c.email, data: structuredClone(c.data) } : null;
    },
    async setCustomerData(id, values) {
      Object.assign(db.customers[id].data, structuredClone(values));
    },
    async getProducts(ids) {
      return ids.map((i) => products[i]).filter(Boolean);
    },
    async adjustWishlistCount(id, d) {
      db.counts[id] = Math.max(0, (db.counts[id] || 0) + d);
      return db.counts[id];
    },
    async getCollectorOwner(h) {
      return db.collectors[h] ? { id: h, owner: { value: db.collectors[h].owner } } : null;
    },
    async upsertCollector(h, fields) {
      db.collectors[h] = fields;
      return { id: h, handle: h };
    },
    async deleteCollector(h) {
      delete db.collectors[h];
    }
  };
}

let admin;
let klaviyoCalls;
let handler;
beforeEach(() => {
  admin = fakeAdmin();
  klaviyoCalls = [];
  handler = createApp({
    config,
    admin,
    klaviyo: { updateProfile: async (email, props) => klaviyoCalls.push({ email, props }) },
    log: { error() {}, warn() {} }
  });
});

async function call(method, url, body, headers = {}) {
  const raw = body === undefined ? '' : typeof body === 'string' ? body : JSON.stringify(body);
  const req = Readable.from(raw ? [Buffer.from(raw)] : []);
  Object.assign(req, { method, url, headers: { 'content-type': 'application/json', ...headers } });
  return new Promise((resolve) => {
    const res = {
      status: 0,
      writeHead(s) { this.status = s; },
      end(b) { resolve({ status: this.status, body: b ? JSON.parse(b) : null }); }
    };
    handler(req, res);
  });
}

test('proxy signature verification', () => {
  const url = new URL(proxyUrl('/proxy/me'), 'http://x');
  assert.equal(verifyProxySignature(url.searchParams, SECRET), true);
  url.searchParams.set('logged_in_customer_id', '43');
  assert.equal(verifyProxySignature(url.searchParams, SECRET), false);
  const stale = new URL(proxyUrl('/proxy/me', { ts: 1000 }), 'http://x');
  assert.equal(verifyProxySignature(stale.searchParams, SECRET), false);
});

test('oauth hmac verification', () => {
  const p = new URLSearchParams({ code: 'c', shop: config.shop, state: 's', timestamp: '1' });
  const msg = [...p.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}=${v}`).join('&');
  p.set('hmac', createHmac('sha256', SECRET).update(msg).digest('hex'));
  assert.equal(verifyOAuthHmac(p, SECRET), true);
  p.set('code', 'tampered');
  assert.equal(verifyOAuthHmac(p, SECRET), false);
});

test('rejects unsigned, logged-out, and non-JSON requests', async () => {
  assert.equal((await call('GET', '/proxy/me?shop=x&logged_in_customer_id=42')).status, 401);
  assert.equal((await call('GET', proxyUrl('/proxy/me', { customer: '' }))).status, 401);
  assert.equal((await call('POST', proxyUrl('/proxy/garage'), 'product_id=1', { 'content-type': 'application/x-www-form-urlencoded' })).status, 415);
  assert.equal((await call('GET', '/nope')).status, 404);
});

test('garage add → stats, Klaviyo sync; remove', async () => {
  let r = await call('POST', proxyUrl('/proxy/garage'), { product_id: '1', status: 'owned' });
  assert.equal(r.status, 200);
  assert.equal(r.body.stats.owned, 1);
  assert.equal(admin.db.customers[42].data.garage[0].group, 'Nissan Skyline R34');
  assert.equal(admin.db.customers[42].data.garage_stats.owned, 1);
  assert.deepEqual(klaviyoCalls.at(-1).props.sc_garage_top_makes, ['Nissan']);
  r = await call('POST', proxyUrl('/proxy/garage'), { product_id: '1', status: null });
  assert.equal(r.body.stats.owned, 0);
  assert.equal((await call('POST', proxyUrl('/proxy/garage'), { product_id: '999', status: 'owned' })).status, 404);
  assert.equal((await call('POST', proxyUrl('/proxy/garage'), { product_id: 'abc', status: 'owned' })).status, 400);
});

test('wishlist toggles move the demand count once per customer', async () => {
  await call('POST', proxyUrl('/proxy/wishlist'), { handle: 'inno64-r34', product_id: '1', saved: true });
  await call('POST', proxyUrl('/proxy/wishlist'), { handle: 'inno64-r34', product_id: '1', saved: true });
  assert.equal(admin.db.counts[1], 1);
  const r = await call('POST', proxyUrl('/proxy/wishlist'), { merge: ['pop-a80', 'inno64-r34'] });
  assert.deepEqual(r.body.wishlist, ['inno64-r34', 'pop-a80']);
  await call('POST', proxyUrl('/proxy/wishlist'), { handle: 'inno64-r34', product_id: '1', saved: false });
  assert.equal(admin.db.counts[1], 0);
});

test('public profile publishes a collector metaobject with a unique slug', async () => {
  admin.db.collectors['r34-hunter'] = { owner: 'someone-else' };
  await call('POST', proxyUrl('/proxy/garage'), { product_id: '1', status: 'owned' });
  const r = await call('POST', proxyUrl('/proxy/profile'), { display_name: 'R34 Hunter', public: true, interests: { makes: ['Nissan'] } });
  assert.equal(r.status, 200);
  assert.equal(r.body.url, '/pages/collector/r34-hunter-2');
  const pub = admin.db.collectors['r34-hunter-2'];
  assert.equal(pub.display_name, 'R34 Hunter');
  assert.equal(pub.garage.length, 1);
  assert.ok(!JSON.stringify(pub).includes('c@test.nz'));
  // Going private removes it
  await call('POST', proxyUrl('/proxy/profile'), { public: false });
  assert.equal(admin.db.collectors['r34-hunter-2'], undefined);
});

test('order webhooks add pre-orders then upgrade to owned on fulfilment', async () => {
  const send = (topic, payload, secret = SECRET) => {
    const raw = JSON.stringify(payload);
    const hmac = createHmac('sha256', secret).update(raw).digest('base64');
    return call('POST', '/webhooks', raw, { 'x-shopify-topic': topic, 'x-shopify-hmac-sha256': hmac });
  };
  const order = {
    customer: { id: 42 },
    line_items: [
      { product_id: 1, properties: [] },
      { product_id: 2, properties: [{ name: '_preorder', value: 'true' }] }
    ]
  };
  assert.equal((await send('orders/create', order, 'wrong')).status, 401);
  await send('orders/create', order);
  let g = admin.db.customers[42].data.garage;
  assert.deepEqual(g.map((e) => [e.pid, e.status]), [['2', 'preordered']]);
  await send('orders/fulfilled', order);
  g = admin.db.customers[42].data.garage;
  assert.deepEqual(g.map((e) => [e.pid, e.status]).sort(), [['1', 'owned'], ['2', 'owned']]);
});

test('auto_garage off skips order sync', async () => {
  await call('POST', proxyUrl('/proxy/profile'), { auto_garage: false });
  const raw = JSON.stringify({ customer: { id: 42 }, line_items: [{ product_id: 1 }] });
  const hmac = createHmac('sha256', SECRET).update(raw).digest('base64');
  const r = await call('POST', '/webhooks', raw, { 'x-shopify-topic': 'orders/fulfilled', 'x-shopify-hmac-sha256': hmac });
  assert.equal(r.body.skipped, 'auto_garage off');
});

test('dashboard is disabled without a password and requires basic auth', async () => {
  assert.equal((await call('GET', '/dashboard')).status, 404);
});

test('dashboard: basic auth gate', async () => {
  const gated = createApp({ config: { ...config, dashboardPassword: 'pw' }, admin, klaviyo: { updateProfile: async () => {} }, log: { error() {}, warn() {} } });
  const req = (auth) => {
    const r = Readable.from([]);
    Object.assign(r, { method: 'GET', url: '/dashboard.json', headers: auth ? { authorization: `Basic ${Buffer.from(auth).toString('base64')}` } : {} });
    return new Promise((resolve) => gated(r, { writeHead(s) { this.s = s; }, end() { resolve(this.s); } }));
  };
  assert.equal(await req(null), 401);
  assert.equal(await req('owner:wrong'), 401);
});
