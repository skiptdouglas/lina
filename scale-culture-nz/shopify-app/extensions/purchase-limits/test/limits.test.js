import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cartValidationsGenerateRun } from '../src/cart_validations_generate_run.js';

const product = (id, extra = {}) => ({
  id: `gid://shopify/Product/${id}`,
  title: `Model ${id}`,
  maxPerCustomer: { value: '2' },
  limitUntil: { value: '2026-10-20' },
  requiresLogin: null,
  ...extra
});
const line = (p, quantity) => ({ quantity, merchandise: { __typename: 'ProductVariant', product: p } });
const input = (lines, { date = '2026-10-18', customer = null } = {}) => ({ shop: { localTime: { date } }, cart: { buyerIdentity: customer ? { customer } : null, lines } });
const messages = (out) => out.operations.flatMap((o) => o.validationAdd.errors.map((e) => e.message));

test('allows quantities within the limit', () => {
  assert.deepEqual(cartValidationsGenerateRun(input([line(product(1), 2)])), { operations: [] });
});

test('blocks over-limit quantities, summed across variant lines', () => {
  const p = product(1);
  const out = cartValidationsGenerateRun(input([line(p, 1), line(p, 2)]));
  assert.equal(out.operations[0].validationAdd.errors[0].target, '$.cart');
  assert.match(messages(out)[0], /limited to 2 per customer/);
});

test('counts earlier purchases for logged-in customers', () => {
  const customer = { id: 'gid://shopify/Customer/42', limitedPurchases: { value: JSON.stringify({ 1: { qty: 1, until: '2026-10-20' } }) } };
  assert.equal(messages(cartValidationsGenerateRun(input([line(product(1), 1)], { customer }))).length, 0);
  assert.match(messages(cartValidationsGenerateRun(input([line(product(1), 2)], { customer })))[0], /already bought 1, so you can add 1 more/);
  const maxed = { ...customer, limitedPurchases: { value: JSON.stringify({ 1: { qty: 2 } }) } };
  assert.match(messages(cartValidationsGenerateRun(input([line(product(1), 1)], { customer: maxed })))[0], /already bought 2\./);
});

test('limit ends after limit_until; blank limit_until keeps it on', () => {
  assert.equal(cartValidationsGenerateRun(input([line(product(1), 5)], { date: '2026-10-21' })).operations.length, 0);
  assert.equal(cartValidationsGenerateRun(input([line(product(1), 5)], { date: '2026-10-20' })).operations.length, 1);
  assert.equal(cartValidationsGenerateRun(input([line(product(1, { limitUntil: null }), 5)], { date: '2030-01-01' })).operations.length, 1);
});

test('requires login when flagged', () => {
  const p = product(1, { requiresLogin: { value: 'true' } });
  assert.match(messages(cartValidationsGenerateRun(input([line(p, 1)])))[0], /log in/);
  assert.equal(cartValidationsGenerateRun(input([line(p, 1)], { customer: { id: 'c', limitedPurchases: null } })).operations.length, 0);
});

test('ignores unlimited products, gift cards and bad history JSON', () => {
  const gift = { quantity: 9, merchandise: { __typename: 'CustomProduct' } };
  const unlimited = product(2, { maxPerCustomer: null });
  const customer = { id: 'c', limitedPurchases: { value: '{not json' } };
  assert.deepEqual(cartValidationsGenerateRun(input([gift, line(unlimited, 50), line(product(1), 2)], { customer })), { operations: [] });
});
