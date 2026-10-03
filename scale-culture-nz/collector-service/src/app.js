// HTTP handler for the collector service. Shopify forwards storefront requests from
// /apps/collector/* to <SERVICE_URL>/proxy/* (app proxy), signed and carrying the
// logged-in customer id, so the customer identity can't be forged from the browser.

import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { buildDashboard, fetchDashboardData, renderDashboard } from './dashboard.js';
import {
  upsertGarage, applyOrderStatus, garageStats, sanitizeProfile, mergeWishlist, publicProfile,
  snapshotFromProduct, handleize, HttpError, applyLimitedPurchases, nzToday
} from './collector.js';
import { verifyProxySignature, verifyWebhook, verifyOAuthHmac, isShopDomain, exchangeOAuthCode } from './shopify.js';
import { klaviyoProperties } from './klaviyo.js';

const MAX_BODY = 64 * 1024;
const OAUTH_SCOPES = 'read_customers,write_customers,read_products,write_products,write_metaobjects,read_metaobjects,read_orders,read_inventory';

export function createApp({ config, admin, klaviyo, saveToken = async () => {}, log = console, now = () => new Date() }) {
  const oauthStates = new Map();
  let dashboardCache = null;

  /** Owner dashboard behind HTTP Basic auth (user "owner", DASHBOARD_PASSWORD). Disabled when unset. */
  function dashboardAuthorized(req) {
    const header = String(req.headers.authorization || '');
    if (!header.startsWith('Basic ')) return false;
    const [, password = ''] = Buffer.from(header.slice(6), 'base64').toString('utf8').split(/:(.*)/s);
    const a = createHmac('sha256', 'cmp').update(password).digest();
    const b = createHmac('sha256', 'cmp').update(config.dashboardPassword).digest();
    return timingSafeEqual(a, b);
  }

  async function dashboard() {
    if (dashboardCache && now().getTime() - dashboardCache.at < 60000) return dashboardCache.data;
    const raw = await fetchDashboardData(admin, { now: now() });
    const data = buildDashboard(raw, { now: now(), lowStockThreshold: config.lowStockThreshold || 3 });
    dashboardCache = { at: now().getTime(), data };
    return data;
  }

  const ownerHash = (customerId) => createHmac('sha256', config.apiSecret).update(`collector:${customerId}`).digest('hex').slice(0, 24);

  async function loadCustomer(customerId) {
    const c = await admin.getCustomer(customerId);
    if (!c) throw new HttpError(404, 'customer not found');
    return {
      email: c.email,
      garage: Array.isArray(c.data.garage) ? c.data.garage : [],
      profile: c.data.profile && typeof c.data.profile === 'object' ? c.data.profile : sanitizeProfile({}),
      wishlist: Array.isArray(c.data.wishlist) ? c.data.wishlist : [],
      limited_purchases: c.data.limited_purchases && typeof c.data.limited_purchases === 'object' ? c.data.limited_purchases : {}
    };
  }

  /** Persists customer data, recomputes stats, syncs the public profile + Klaviyo. */
  async function saveCustomer(customerId, state, changed) {
    const stats = garageStats(state.garage);
    const values = { garage_stats: stats };
    for (const key of changed) values[key] = state[key];
    if (changed.includes('profile') || changed.includes('garage')) {
      state.profile = await syncPublicProfile(customerId, state.profile, state.garage);
      values.profile = state.profile;
    }
    await admin.setCustomerData(customerId, values);
    await klaviyo.updateProfile(state.email, klaviyoProperties({ profile: state.profile, stats, wishlist: state.wishlist }));
    return stats;
  }

  /** Public collector profiles are `collector` metaobjects rendered by the theme at /pages/collector/<handle>. */
  async function syncPublicProfile(customerId, profile, garage) {
    const owner = ownerHash(customerId);
    if (!profile.public) {
      if (profile.slug) await admin.deleteCollector(profile.slug);
      return { ...profile, slug: '' };
    }
    let slug = profile.slug;
    if (!slug) {
      const base = handleize(profile.display_name) || 'collector';
      for (let i = 1; i <= 50 && !slug; i++) {
        const candidate = i === 1 ? base : `${base}-${i}`;
        const existing = await admin.getCollectorOwner(candidate);
        if (!existing || existing.owner?.value === owner) slug = candidate;
      }
      if (!slug) throw new HttpError(409, 'display name unavailable — try another');
    }
    const pub = publicProfile(profile, garage);
    await admin.upsertCollector(slug, {
      owner,
      display_name: pub.display_name,
      bio: pub.bio,
      location: pub.location,
      stats: pub.stats,
      garage: pub.garage
    });
    return { ...profile, slug };
  }

  async function snapshot(productId) {
    const [product] = await admin.getProducts([productId]);
    if (!product) throw new HttpError(404, 'product not found');
    return snapshotFromProduct(product);
  }

  const routes = {
    'GET /proxy/me': async ({ customerId }) => {
      const s = await loadCustomer(customerId);
      return { profile: s.profile, wishlist: s.wishlist, stats: garageStats(s.garage), garage: s.garage };
    },

    'POST /proxy/garage': async ({ customerId, body }) => {
      const productId = String(body.product_id || '');
      if (!/^\d+$/.test(productId)) throw new HttpError(400, 'product_id required');
      const status = body.status ?? null;
      const s = await loadCustomer(customerId);
      const snap = status == null ? { pid: productId } : await snapshot(productId);
      s.garage = upsertGarage(s.garage, snap, status, { note: body.note });
      const stats = await saveCustomer(customerId, s, ['garage']);
      return { status, stats };
    },

    'POST /proxy/profile': async ({ customerId, body }) => {
      const s = await loadCustomer(customerId);
      s.profile = sanitizeProfile(body, s.profile);
      await saveCustomer(customerId, s, ['profile']);
      return { profile: s.profile, url: s.profile.slug ? `/pages/collector/${s.profile.slug}` : null };
    },

    'POST /proxy/wishlist': async ({ customerId, body }) => {
      const s = await loadCustomer(customerId);
      const before = new Set(s.wishlist);
      if (Array.isArray(body.merge)) {
        s.wishlist = mergeWishlist(s.wishlist, body.merge);
      } else {
        const handle = String(body.handle || '');
        if (!/^[a-z0-9-]{1,255}$/.test(handle)) throw new HttpError(400, 'handle required');
        s.wishlist = body.saved ? mergeWishlist([handle], s.wishlist) : s.wishlist.filter((h) => h !== handle);
        // Demand counter only moves when this customer's membership actually changes
        const productId = String(body.product_id || '');
        if (/^\d+$/.test(productId) && before.has(handle) !== Boolean(body.saved)) {
          await admin.adjustWishlistCount(productId, body.saved ? 1 : -1);
        }
      }
      await saveCustomer(customerId, s, ['wishlist']);
      return { wishlist: s.wishlist };
    }
  };

  async function handleWebhook(req, raw) {
    if (!verifyWebhook(raw, req.headers['x-shopify-hmac-sha256'], config.apiSecret)) throw new HttpError(401, 'bad hmac');
    const topic = req.headers['x-shopify-topic'];
    const payload = JSON.parse(raw.toString('utf8') || '{}');

    if (topic === 'orders/create' || topic === 'orders/fulfilled' || topic === 'orders/cancelled') {
      const customerId = payload.customer?.id;
      if (!customerId) return { ok: true };
      const lines = (payload.line_items || []).filter((l) => l.product_id);
      if (!lines.length) return { ok: true };
      const products = await admin.getProducts([...new Set(lines.map((l) => String(l.product_id)))]);
      const byId = new Map(products.map((p) => [String(p.id), p]));
      const s = await loadCustomer(customerId);
      const changed = [];
      const result = {};

      // Drop-day limits: count limited units bought (or returned on cancellation)
      if (topic !== 'orders/fulfilled') {
        const r = applyLimitedPurchases(s.limited_purchases, payload, byId, { today: nzToday(now()), cancelled: topic === 'orders/cancelled' });
        if (r.changed) {
          s.limited_purchases = r.history;
          changed.push('limited_purchases');
        }
      }

      // My Garage: pre-orders on create, everything owned once fulfilled
      if (topic !== 'orders/cancelled') {
        const isPre = (l) => (l.properties || []).some((p) => p.name === '_preorder' && String(p.value) === 'true');
        const targets = topic === 'orders/fulfilled' ? lines.map((l) => [l, 'owned']) : lines.filter(isPre).map((l) => [l, 'preordered']);
        if (targets.length && s.profile.auto_garage === false) result.skipped = 'auto_garage off';
        else if (targets.length) {
          for (const [line, status] of targets) {
            const p = byId.get(String(line.product_id));
            if (p) s.garage = applyOrderStatus(s.garage, snapshotFromProduct(p), status);
          }
          changed.push('garage');
        }
      }

      if (changed.length) await saveCustomer(customerId, s, changed);
      return { ok: true, ...result };
    }

    // Privacy compliance webhooks
    if (topic === 'customers/redact') {
      const customerId = payload.customer?.id;
      if (customerId) {
        const c = await admin.getCustomer(customerId).catch(() => null);
        if (c?.data?.profile?.slug) await admin.deleteCollector(c.data.profile.slug);
      }
      return { ok: true };
    }
    // customers/data_request: all data lives in Shopify customer metafields, which Shopify exports itself.
    // shop/redact: nothing stored outside Shopify.
    return { ok: true };
  }

  async function handleAuth(url, res) {
    const shop = url.searchParams.get('shop');
    if (url.pathname === '/auth') {
      if (shop !== config.shop || !isShopDomain(shop)) throw new HttpError(400, 'unknown shop');
      const state = randomBytes(16).toString('hex');
      oauthStates.set(state, Date.now());
      const redirect = new URL(`https://${shop}/admin/oauth/authorize`);
      redirect.searchParams.set('client_id', config.apiKey);
      redirect.searchParams.set('scope', OAUTH_SCOPES);
      redirect.searchParams.set('redirect_uri', `${config.serviceUrl}/auth/callback`);
      redirect.searchParams.set('state', state);
      res.writeHead(302, { Location: redirect.toString() });
      return res.end();
    }
    // /auth/callback
    const state = url.searchParams.get('state');
    if (!oauthStates.has(state) || Date.now() - oauthStates.get(state) > 600000) throw new HttpError(400, 'bad state');
    oauthStates.delete(state);
    if (shop !== config.shop || !verifyOAuthHmac(url.searchParams, config.apiSecret)) throw new HttpError(401, 'bad hmac');
    const token = await exchangeOAuthCode({ shop, code: url.searchParams.get('code'), clientId: config.apiKey, clientSecret: config.apiSecret });
    await saveToken(token);
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('Collector service installed. You can close this window.');
  }

  return async function handler(req, res) {
    const url = new URL(req.url, 'http://localhost');
    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      res.end(JSON.stringify(body));
    };
    try {
      if (url.pathname === '/health') return send(200, { ok: true });
      if (url.pathname === '/auth' || url.pathname === '/auth/callback') return await handleAuth(url, res);
      if (url.pathname === '/dashboard' || url.pathname === '/dashboard.json') {
        if (!config.dashboardPassword) throw new HttpError(404, 'not found');
        if (!dashboardAuthorized(req)) {
          res.writeHead(401, { 'WWW-Authenticate': 'Basic realm="Scale Culture owner", charset="UTF-8"' });
          return res.end();
        }
        const data = await dashboard();
        if (url.pathname === '/dashboard.json') return send(200, data);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY' });
        return res.end(renderDashboard(data, { shop: config.shop, lowStockThreshold: config.lowStockThreshold || 3 }));
      }

      const raw = req.method === 'POST' ? await readBody(req) : Buffer.alloc(0);
      if (url.pathname === '/webhooks' && req.method === 'POST') return send(200, await handleWebhook(req, raw));

      const route = routes[`${req.method} ${url.pathname}`];
      if (!route) throw new HttpError(404, 'not found');
      if (!verifyProxySignature(url.searchParams, config.apiSecret)) throw new HttpError(401, 'bad signature');
      if (url.searchParams.get('shop') !== config.shop) throw new HttpError(403, 'wrong shop');
      const customerId = url.searchParams.get('logged_in_customer_id');
      if (!customerId) throw new HttpError(401, 'login required');

      let body = {};
      if (req.method === 'POST') {
        // JSON-only blocks cross-site form posts (they can't set this content type without CORS preflight)
        if (!String(req.headers['content-type'] || '').startsWith('application/json')) throw new HttpError(415, 'json required');
        try {
          body = JSON.parse(raw.toString('utf8') || '{}');
        } catch {
          throw new HttpError(400, 'invalid json');
        }
      }
      return send(200, await route({ customerId, body }));
    } catch (e) {
      const status = e instanceof HttpError ? e.status : 500;
      if (status === 500) log.error(e);
      return send(status, { error: status === 500 ? 'internal error' : e.message });
    }
  };
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new HttpError(413, 'body too large'));
        req.destroy();
      } else chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}
