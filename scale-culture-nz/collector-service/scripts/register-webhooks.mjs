#!/usr/bin/env node
// Registers the order + privacy webhooks the collector service listens to.
//   node scripts/register-webhooks.mjs     (same env as the service)
import { loadConfig, createTokenStore } from '../src/server.js';
import { createAdminClient } from '../src/shopify.js';

const config = loadConfig();
const tokens = await createTokenStore(config);
const admin = createAdminClient({ shop: config.shop, token: tokens.get, apiVersion: config.apiVersion });
const callback = `${config.serviceUrl}/webhooks`;
for (const topic of ['ORDERS_CREATE', 'ORDERS_FULFILLED', 'ORDERS_CANCELLED']) {
  const errors = await admin.registerWebhook(topic, callback);
  console.log(errors.length ? `· ${topic}: ${errors.map((e) => e.message).join('; ')}` : `✓ ${topic} → ${callback}`);
}
console.log('Privacy webhooks (customers/redact etc.) are configured in the app settings, pointing at the same URL.');
