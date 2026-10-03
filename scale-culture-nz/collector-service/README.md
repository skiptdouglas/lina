# Collector service

This is the small backend behind the Phase 2 collector features: **My Garage**, **collector
profiles**, the **account-synced wishlist with demand counts**, and the **Klaviyo interest
sync**. It is plain Node 20+ with no dependencies, so `npm install` isn't needed.

```
storefront ──/apps/collector/*──▶ Shopify app proxy ──signed──▶ this service ──Admin API──▶ customer/product metafields
                                                                     │                       collector metaobjects
                                                                     └──────────────────────▶ Klaviyo profile properties
Shopify ──orders/create, orders/fulfilled webhooks──▶ /webhooks  (auto-adds purchases to My Garage)
```

All data lives in Shopify, so the service is stateless apart from its Admin API token:

| Data | Where |
|---|---|
| Garage, stats, profile, wishlist | Customer metafields `scale.garage`, `scale.garage_stats`, `scale.profile`, `scale.wishlist` (JSON) |
| Wishlist demand | Product metafield `scale.wishlist_count` |
| Public profiles | `collector` metaobjects, rendered by the theme at `/pages/collector/<handle>` |

## Security

- **Customer identity.** It comes only from the `logged_in_customer_id` that Shopify adds and
  signs on app-proxy requests. The service checks the HMAC signature and rejects requests
  older than 5 minutes.
- **Cross-site requests.** Write endpoints accept only `application/json`, so a third-party
  site can't post as the customer without a CORS preflight.
- **Webhooks.** They are checked with `X-Shopify-Hmac-Sha256`. OAuth installs check `state`
  and the HMAC.
- **Public profiles.** They hold no email address, customer ID, notes or prices. The owner
  link is an HMAC of the customer ID.

## Endpoints

Shopify forwards `/apps/collector/<path>` on the storefront to `/proxy/<path>` here.

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/proxy/me` | | Garage, stats, profile and wishlist |
| POST | `/proxy/garage` | `{product_id, status: "owned"\|"wanted"\|"preordered"\|null, note?}` | Set or clear a garage entry |
| POST | `/proxy/profile` | `{display_name, bio, location, public, show_wanted, auto_garage, interests:{makes,scales,brands,categories}}` | Save the profile and publish or unpublish the public page |
| POST | `/proxy/wishlist` | `{handle, product_id, saved}` or `{merge:[handles]}` | Sync the wishlist and adjust the demand count |
| POST | `/webhooks` | Shopify webhook | `orders/create` marks pre-ordered items, `orders/fulfilled` marks items owned, `customers/redact` removes the public profile |
| GET | `/auth`, `/auth/callback` | | One-time OAuth install that stores the Admin token |
| GET | `/health` | | Liveness check |

## Setup

1. **Create the app.** In the Shopify Dev Dashboard, create a custom app for the store and
   note its client ID and secret.
   - **Scopes:** `read_customers, write_customers, read_products, write_products,
     read_metaobjects, write_metaobjects, read_orders`
   - **App proxy:** prefix `apps`, subpath `collector`, URL `https://<SERVICE_URL>/proxy`
   - **Redirect URL:** `https://<SERVICE_URL>/auth/callback`
   - **Privacy (compliance) webhooks:** `https://<SERVICE_URL>/webhooks`
2. **Deploy.** Any HTTPS host works: Fly.io, Render, Railway or a small VPS. Mount a
   persistent volume at `/data` for the token file, or set `SHOPIFY_ADMIN_TOKEN` instead.

   ```bash
   cp .env.example .env   # fill in
   docker build -t collector . && docker run --env-file .env -p 8787:8787 -v collector-data:/data collector
   ```
3. **Install.** Open `https://<SERVICE_URL>/auth?shop=<store>.myshopify.com` and approve.
4. **Set up the store.** Run `node ../scripts/setup-store.mjs` to create the customer
   metafields and the `collector` metaobject, then `npm run register-webhooks`.
5. **Turn it on in the theme.** Theme settings → *Collector features* → enable, and add the
   Klaviyo public key.

## Tests

```bash
npm test     # node:test — signatures, garage rules, profiles, wishlist counts, webhooks
```

## Known limits

- **Wishlist count drift.** The count is read, then written. Two collectors saving the same
  model in the same instant can drift it by one, which is fine for a demand signal. To
  correct it, run a nightly recount over customer wishlists.
- **Garage size.** Capped at 2,000 entries per collector to stay well inside metafield size
  limits.
