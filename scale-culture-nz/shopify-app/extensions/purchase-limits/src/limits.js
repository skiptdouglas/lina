// Drop-day purchase limits (pure logic, shared by the Function and its tests).
//
// A product is limited when scale.max_per_customer > 0 and today (shop local
// date) is on or before scale.limit_until (or limit_until is blank). Quantities
// are summed across a product's variants. Logged-in customers also count units
// already bought on earlier orders (customer metafield scale.limited_purchases,
// kept up to date by the collector service's order webhooks).

const numericId = (gid) => String(gid || '').split('/').pop();

function parseHistory(value) {
  try {
    const parsed = JSON.parse(value || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function limitErrors(input) {
  const today = input?.shop?.localTime?.date || '';
  const customer = input?.cart?.buyerIdentity?.customer || null;
  const history = parseHistory(customer?.limitedPurchases?.value);

  const limited = new Map();
  for (const line of input?.cart?.lines || []) {
    const m = line.merchandise;
    if (!m || m.__typename !== 'ProductVariant') continue;
    const p = m.product;
    const max = parseInt(p.maxPerCustomer?.value ?? '', 10);
    if (!(max > 0)) continue;
    const until = p.limitUntil?.value || '';
    if (until && today && today > until) continue; // limit window over
    const entry = limited.get(p.id) || { title: p.title, max, qty: 0, requiresLogin: p.requiresLogin?.value === 'true' };
    entry.qty += line.quantity;
    limited.set(p.id, entry);
  }

  const errors = [];
  for (const [id, e] of limited) {
    if (e.requiresLogin && !customer) {
      errors.push(`${e.title} is a limited release — please log in to buy it.`);
      continue;
    }
    const bought = Number(history[numericId(id)]?.qty || 0);
    const remaining = Math.max(0, e.max - bought);
    if (e.qty > remaining) {
      errors.push(
        bought > 0
          ? remaining > 0
            ? `${e.title} is limited to ${e.max} per customer. You've already bought ${bought}, so you can add ${remaining} more.`
            : `${e.title} is limited to ${e.max} per customer, and you've already bought ${bought}.`
          : `${e.title} is limited to ${e.max} per customer. Please reduce the quantity to ${e.max}.`
      );
    }
  }
  return errors;
}
