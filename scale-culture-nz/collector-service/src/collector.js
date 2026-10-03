// Pure domain logic for Phase 2 collector features (SOP §19 My Garage, §20 wishlist,
// §37 collector profiles). No I/O here so it can be unit tested in isolation.

export const GARAGE_STATUSES = ['owned', 'wanted', 'preordered'];
export const MAX_GARAGE = 2000;
export const MAX_WISHLIST = 500;
const TOP_MAKES = 4;

/**
 * Product snapshot stored on each garage entry so the garage renders in Liquid
 * without per-product lookups (Liquid's all_products is capped at 20 per page).
 */
export function snapshotFromProduct(p) {
  const mf = (key) => p.metafields?.[key] ?? null;
  const make = mf('vehicle_make');
  const model = mf('vehicle_model');
  const gen = mf('vehicle_generation');
  return {
    pid: String(p.id),
    handle: p.handle,
    title: p.title,
    card_title: mf('card_title') || p.title,
    vendor: p.vendor || '',
    image: p.image || '',
    scale: mf('scale') || '',
    make: make || 'Other',
    model: model || '',
    gen: gen || '',
    colour: mf('colour') || '',
    group: [make, model, gen].filter(Boolean).join(' ') || p.title
  };
}

/** Insert, update or remove (status = null) a garage entry. Returns a new array. */
export function upsertGarage(garage, snapshot, status, { note, now = new Date() } = {}) {
  const list = Array.isArray(garage) ? garage.filter((e) => e && e.pid) : [];
  const idx = list.findIndex((e) => e.pid === snapshot.pid);
  if (status == null) {
    if (idx >= 0) list.splice(idx, 1);
    return list;
  }
  if (!GARAGE_STATUSES.includes(status)) throw new HttpError(400, `status must be one of ${GARAGE_STATUSES.join(', ')}`);
  const prev = idx >= 0 ? list[idx] : null;
  const entry = {
    ...prev,
    ...snapshot,
    status,
    added: prev?.added || now.toISOString(),
    updated: now.toISOString(),
    note: typeof note === 'string' ? note.slice(0, 140) : prev?.note || ''
  };
  if (idx >= 0) list[idx] = entry;
  else {
    if (list.length >= MAX_GARAGE) throw new HttpError(400, 'garage is full');
    list.unshift(entry);
  }
  return list;
}

/**
 * Status changes driven by orders: a pre-order purchase → preordered, a fulfilled
 * line → owned. Never downgrades owned, never overrides an entry the collector removed
 * (we only add when absent or upgrade wanted → preordered → owned).
 */
export function applyOrderStatus(garage, snapshot, status, opts) {
  const rank = { wanted: 0, preordered: 1, owned: 2 };
  const existing = (garage || []).find((e) => e.pid === snapshot.pid);
  if (existing && rank[existing.status] >= rank[status]) return garage;
  return upsertGarage(garage, snapshot, status, opts);
}

/** "Models owned: 84 — Nissan: 21, Porsche: 17, Toyota: 12, BMW: 8, Other: 26" */
export function garageStats(garage) {
  const list = garage || [];
  const count = (s) => list.filter((e) => e.status === s).length;
  const owned = list.filter((e) => e.status === 'owned');

  const byMake = new Map();
  for (const e of owned) byMake.set(e.make, (byMake.get(e.make) || 0) + 1);
  const sorted = [...byMake.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const top = sorted.filter(([m]) => m !== 'Other').slice(0, TOP_MAKES);
  const otherCount = owned.length - top.reduce((n, [, c]) => n + c, 0);
  const makes = top.map(([make, count]) => ({ make, count }));
  if (otherCount > 0) makes.push({ make: 'Other', count: otherCount });

  // Collections like "R34 Collection": groups with 2+ entries in any status
  const groups = new Map();
  for (const e of list) groups.set(e.group, (groups.get(e.group) || 0) + 1);
  const collections = [...groups.entries()]
    .filter(([, n]) => n >= 2)
    .sort((a, b) => b[1] - a[1])
    .map(([group, n]) => ({ group, count: n }));

  const scales = new Map();
  for (const e of owned) if (e.scale) scales.set(e.scale, (scales.get(e.scale) || 0) + 1);

  return {
    owned: owned.length,
    wanted: count('wanted'),
    preordered: count('preordered'),
    makes,
    collections,
    top_make_handles: top.map(([m]) => handleize(m)),
    top_scale: [...scales.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || ''
  };
}

const INTEREST_LIMIT = 30;
const cleanList = (v) =>
  Array.isArray(v)
    ? [...new Set(v.filter((x) => typeof x === 'string').map((x) => x.trim().slice(0, 40)).filter(Boolean))].slice(0, INTEREST_LIMIT)
    : [];

/** Validates and normalises a profile submitted from the storefront. */
export function sanitizeProfile(input, prev = {}) {
  if (!input || typeof input !== 'object') throw new HttpError(400, 'profile must be an object');
  const displayName = String(input.display_name ?? prev.display_name ?? '').trim().slice(0, 40);
  const isPublic = Boolean(input.public ?? prev.public ?? false);
  if (isPublic && displayName.length < 2) throw new HttpError(400, 'a public profile needs a display name');
  return {
    display_name: displayName,
    bio: String(input.bio ?? prev.bio ?? '').trim().slice(0, 280),
    location: String(input.location ?? prev.location ?? '').trim().slice(0, 40),
    public: isPublic,
    show_wanted: Boolean(input.show_wanted ?? prev.show_wanted ?? true),
    auto_garage: Boolean(input.auto_garage ?? prev.auto_garage ?? true),
    interests: {
      makes: cleanList(input.interests?.makes ?? prev.interests?.makes),
      scales: cleanList(input.interests?.scales ?? prev.interests?.scales),
      brands: cleanList(input.interests?.brands ?? prev.interests?.brands),
      categories: cleanList(input.interests?.categories ?? prev.interests?.categories)
    },
    slug: prev.slug || ''
  };
}

/** Merge local (browser) and server wishlists; server order first, de-duplicated. */
export function mergeWishlist(server, local) {
  const clean = (l) => (Array.isArray(l) ? l.filter((h) => typeof h === 'string' && /^[a-z0-9-]{1,255}$/.test(h)) : []);
  return [...new Set([...clean(server), ...clean(local)])].slice(0, MAX_WISHLIST);
}

/** Public profile data — nothing private (no email, no customer id, no notes). */
export function publicProfile(profile, garage) {
  const visible = (garage || []).filter((e) => e.status === 'owned' || (profile.show_wanted && e.status === 'wanted'));
  return {
    display_name: profile.display_name,
    bio: profile.bio,
    location: profile.location,
    stats: garageStats(visible),
    garage: visible.map(({ handle, card_title, vendor, image, scale, make, model, gen, colour, group, status }) => ({
      handle, card_title, vendor, image, scale, make, model, gen, colour, group, status
    }))
  };
}

export function handleize(s) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/:/g, '-')
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
}

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

/**
 * Drop-day purchase limits: running count of units each customer has bought of
 * products that currently have a per-customer limit. The purchase-limits checkout
 * Function reads this to enforce limits across separate orders.
 *
 * history: { "<productId>": { qty, until }, _seen: { "<orderId>": "create" | "cancel" } }
 * Webhooks can be retried, so each order is applied at most once per direction.
 */
export function applyLimitedPurchases(history, order, productsById, { today, cancelled = false } = {}) {
  const next = { ...(history && typeof history === 'object' ? history : {}) };
  const seen = { ...(next._seen || {}) };
  const orderKey = String(order.id || '');
  const direction = cancelled ? 'cancel' : 'create';
  if (orderKey && (seen[orderKey] === direction || (direction === 'create' && seen[orderKey] === 'cancel'))) {
    return { history: next, changed: false };
  }

  let changed = false;
  for (const line of order.line_items || []) {
    const pid = String(line.product_id || '');
    const p = productsById.get(pid);
    const max = Number(p?.metafields?.max_per_customer || 0);
    const until = p?.metafields?.limit_until || '';
    if (!(max > 0) || (until && today > until)) continue;
    const prev = next[pid] || { qty: 0, until };
    const qty = Math.max(0, prev.qty + (cancelled ? -1 : 1) * Number(line.quantity || 0));
    next[pid] = { qty, until };
    changed = true;
  }

  // Drop expired entries so the metafield stays small
  for (const [k, v] of Object.entries(next)) {
    if (k !== '_seen' && v && v.until && today > v.until) {
      delete next[k];
      changed = true;
    }
  }
  if (changed && orderKey) {
    seen[orderKey] = direction;
    const keys = Object.keys(seen);
    for (const k of keys.slice(0, Math.max(0, keys.length - 200))) delete seen[k];
    next._seen = seen;
  }
  return { history: next, changed };
}

export const nzToday = (now = new Date()) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Pacific/Auckland', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
