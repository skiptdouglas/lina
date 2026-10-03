// Shopify plumbing: app-proxy + webhook signature checks, OAuth install, and the
// Admin GraphQL calls the collector service needs.

import { createHmac, timingSafeEqual } from 'node:crypto';

const NS = 'scale';
const PROXY_MAX_AGE_S = 300;

const safeEqual = (a, b) => {
  const ba = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ba.length === bb.length && timingSafeEqual(ba, bb);
};

/**
 * App proxy signature: every query param except `signature`, as key=value
 * (repeated keys joined with ","), sorted, concatenated, HMAC-SHA256 hex.
 * https://shopify.dev/docs/apps/build/online-store/display-dynamic-data#calculate-a-digital-signature
 */
export function verifyProxySignature(searchParams, secret, { now = Date.now() } = {}) {
  const signature = searchParams.get('signature');
  if (!signature) return false;
  const grouped = new Map();
  for (const [k, v] of searchParams) {
    if (k === 'signature') continue;
    grouped.set(k, [...(grouped.get(k) || []), v]);
  }
  const message = [...grouped.entries()]
    .map(([k, v]) => `${k}=${v.join(',')}`)
    .sort()
    .join('');
  const digest = createHmac('sha256', secret).update(message).digest('hex');
  if (!safeEqual(digest, signature)) return false;
  const ts = Number(searchParams.get('timestamp'));
  return Number.isFinite(ts) && Math.abs(now / 1000 - ts) <= PROXY_MAX_AGE_S;
}

/** Webhook HMAC: base64 HMAC-SHA256 of the raw body. */
export function verifyWebhook(rawBody, hmacHeader, secret) {
  if (!hmacHeader) return false;
  const digest = createHmac('sha256', secret).update(rawBody).digest('base64');
  return safeEqual(digest, hmacHeader);
}

/** OAuth callback HMAC: hex over the sorted query string without `hmac`. */
export function verifyOAuthHmac(searchParams, secret) {
  const hmac = searchParams.get('hmac');
  if (!hmac) return false;
  const message = [...searchParams.entries()]
    .filter(([k]) => k !== 'hmac' && k !== 'signature')
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join('&');
  return safeEqual(createHmac('sha256', secret).update(message).digest('hex'), hmac);
}

export const isShopDomain = (shop) => /^[a-z0-9][a-z0-9-]*\.myshopify\.com$/.test(shop || '');

export async function exchangeOAuthCode({ shop, code, clientId, clientSecret, fetchImpl = fetch }) {
  const res = await fetchImpl(`https://${shop}/admin/oauth/access_token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, code })
  });
  if (!res.ok) throw new Error(`token exchange failed: ${res.status}`);
  return (await res.json()).access_token;
}

export function createAdminClient({ shop, token, apiVersion = '2025-10', fetchImpl = fetch }) {
  async function gql(query, variables = {}) {
    const res = await fetchImpl(`https://${shop}/admin/api/${apiVersion}/graphql.json`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Shopify-Access-Token': token() },
      body: JSON.stringify({ query, variables })
    });
    const body = await res.json();
    if (!res.ok || body.errors) throw new Error(`Admin API: ${JSON.stringify(body.errors || res.status)}`);
    return body.data;
  }

  const userErrors = (r) => {
    if (r?.userErrors?.length) throw new Error(r.userErrors.map((e) => e.message).join('; '));
    return r;
  };

  const parseMetafields = (nodes) =>
    Object.fromEntries(
      (nodes || []).map((n) => {
        try {
          return [n.key, n.type === 'json' || n.type === 'number_integer' ? JSON.parse(n.value) : n.value];
        } catch {
          return [n.key, n.value];
        }
      })
    );

  return {
    gql,

    async getCustomer(customerId) {
      const data = await gql(
        `query($id: ID!) { customer(id: $id) { id email firstName metafields(namespace: "${NS}", first: 20) { nodes { key type value } } } }`,
        { id: `gid://shopify/Customer/${customerId}` }
      );
      if (!data.customer) return null;
      return { ...data.customer, data: parseMetafields(data.customer.metafields.nodes) };
    },

    async setCustomerData(customerId, values) {
      const metafields = Object.entries(values).map(([key, value]) => ({
        ownerId: `gid://shopify/Customer/${customerId}`,
        namespace: NS,
        key,
        type: 'json',
        value: JSON.stringify(value)
      }));
      const data = await gql(
        `mutation($m: [MetafieldsSetInput!]!) { metafieldsSet(metafields: $m) { userErrors { field message } } }`,
        { m: metafields }
      );
      userErrors(data.metafieldsSet);
    },

    /** Products with the fields needed for garage snapshots. */
    async getProducts(productIds) {
      if (!productIds.length) return [];
      const data = await gql(
        `query($ids: [ID!]!) { nodes(ids: $ids) { ... on Product {
          id legacyResourceId handle title vendor
          featuredMedia { preview { image { url } } }
          metafields(namespace: "${NS}", first: 30) { nodes { key type value } }
        } } }`,
        { ids: productIds.map((id) => `gid://shopify/Product/${id}`) }
      );
      return data.nodes.filter(Boolean).map((p) => ({
        id: p.legacyResourceId,
        handle: p.handle,
        title: p.title,
        vendor: p.vendor,
        image: p.featuredMedia?.preview?.image?.url || '',
        metafields: parseMetafields(p.metafields.nodes)
      }));
    },

    /** Adjusts the wishlist demand counter shown on product pages (SOP §20). */
    async adjustWishlistCount(productId, delta) {
      const gid = `gid://shopify/Product/${productId}`;
      const data = await gql(`query($id: ID!) { product(id: $id) { metafield(namespace: "${NS}", key: "wishlist_count") { value } } }`, { id: gid });
      if (!data.product) return null;
      const next = Math.max(0, (parseInt(data.product.metafield?.value || '0', 10) || 0) + delta);
      const res = await gql(
        `mutation($m: [MetafieldsSetInput!]!) { metafieldsSet(metafields: $m) { userErrors { message } } }`,
        { m: [{ ownerId: gid, namespace: NS, key: 'wishlist_count', type: 'number_integer', value: String(next) }] }
      );
      userErrors(res.metafieldsSet);
      return next;
    },

    async getCollectorOwner(handle) {
      const data = await gql(
        `query($h: MetaobjectHandleInput!) { metaobjectByHandle(handle: $h) { id owner: field(key: "owner") { value } } }`,
        { h: { type: 'collector', handle } }
      );
      return data.metaobjectByHandle;
    },

    async upsertCollector(handle, fields) {
      const data = await gql(
        `mutation($h: MetaobjectHandleInput!, $m: MetaobjectUpsertInput!) {
          metaobjectUpsert(handle: $h, metaobject: $m) { metaobject { id handle } userErrors { message } }
        }`,
        {
          h: { type: 'collector', handle },
          m: {
            fields: Object.entries(fields).map(([key, value]) => ({ key, value: typeof value === 'string' ? value : JSON.stringify(value) })),
            capabilities: { publishable: { status: 'ACTIVE' } }
          }
        }
      );
      return userErrors(data.metaobjectUpsert).metaobject;
    },

    async deleteCollector(handle) {
      const existing = await this.getCollectorOwner(handle);
      if (!existing) return;
      const data = await gql(`mutation($id: ID!) { metaobjectDelete(id: $id) { userErrors { message } } }`, { id: existing.id });
      userErrors(data.metaobjectDelete);
    },

    async registerWebhook(topic, callbackUrl) {
      const data = await gql(
        `mutation($t: WebhookSubscriptionTopic!, $u: URL!) {
          webhookSubscriptionCreate(topic: $t, webhookSubscription: { callbackUrl: $u, format: JSON }) { userErrors { message } }
        }`,
        { t: topic, u: callbackUrl }
      );
      return data.webhookSubscriptionCreate.userErrors;
    }
  };
}
