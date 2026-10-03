// Entry point: `node src/server.js`. Configuration comes from the environment (see .env.example).
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { createApp } from './app.js';
import { createAdminClient } from './shopify.js';
import { createKlaviyo } from './klaviyo.js';

export function loadConfig(env = process.env) {
  const required = ['SHOPIFY_STORE', 'SHOPIFY_API_KEY', 'SHOPIFY_API_SECRET', 'SERVICE_URL'];
  const missing = required.filter((k) => !env[k]);
  if (missing.length) throw new Error(`Missing env: ${missing.join(', ')}`);
  return {
    shop: env.SHOPIFY_STORE,
    apiKey: env.SHOPIFY_API_KEY,
    apiSecret: env.SHOPIFY_API_SECRET,
    apiVersion: env.SHOPIFY_API_VERSION || '2025-10',
    serviceUrl: env.SERVICE_URL.replace(/\/$/, ''),
    klaviyoKey: env.KLAVIYO_PRIVATE_KEY || '',
    dataDir: env.DATA_DIR || '.data',
    port: Number(env.PORT || 8787),
    envToken: env.SHOPIFY_ADMIN_TOKEN || ''
  };
}

export async function createTokenStore(config) {
  const file = join(config.dataDir, 'token.json');
  let token = config.envToken;
  if (!token) {
    try {
      token = JSON.parse(await readFile(file, 'utf8')).token;
    } catch {
      /* not installed yet — visit /auth?shop=<store> */
    }
  }
  return {
    get: () => {
      if (!token) throw new Error('No Admin API token — install the app via /auth?shop=' + config.shop);
      return token;
    },
    async save(t) {
      token = t;
      await mkdir(config.dataDir, { recursive: true });
      await writeFile(file, JSON.stringify({ token: t }), { mode: 0o600 });
    }
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const config = loadConfig();
  const tokens = await createTokenStore(config);
  const admin = createAdminClient({ shop: config.shop, token: tokens.get, apiVersion: config.apiVersion });
  const klaviyo = createKlaviyo({ apiKey: config.klaviyoKey });
  const handler = createApp({ config, admin, klaviyo, saveToken: tokens.save });
  createServer(handler).listen(config.port, () => {
    console.log(`collector service on :${config.port} for ${config.shop}${klaviyo.enabled ? ' (klaviyo on)' : ''}`);
  });
}
