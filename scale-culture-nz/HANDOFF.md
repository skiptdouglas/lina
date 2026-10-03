# Handoff: Scale Culture NZ

This is the code and tooling for **Scale Culture NZ**, a premium New Zealand online store for
imported die-cast models, plastic kits and automotive collectibles. It is built on Shopify,
following the *Scale Culture NZ – Website Build SOP*.

- **Live preview** (sample data, view-only): https://claude.ai/artifact/XMDwoETVUrSZdTGJ6KQC6a
  The link is private to the owner's Claude account; share it from the page's Share menu.
- **Screenshots:** [`docs/screenshots/`](docs/screenshots/)
- **SOP section → where it is built:** [`docs/sop-coverage.md`](docs/sop-coverage.md)

## 1. Status

| Area | State |
|---|---|
| Phase 1 MVP (§36): theme, stock states, pre-orders, drops, brands, filters, search, cart, wishlist, accounts, SEO | **Built** |
| Phase 2 (§37): My Garage, collector profiles, synced wishlist with demand counts, restock alerts, drop reminders, recommendations, reviews | **Built** |
| Extras: journal, slide-out cart and quick add, owner dashboard, bundles, drop-day purchase limits | **Built** |
| Phase 3 (§38): app, valuation, marketplace, loyalty, etc. | Not started |
| **Running on a real Shopify store** | **Not yet.** Nothing has been deployed. See section 3. |

### What has been verified

- **Tests:** automated tests run in CI (`.github/workflows/ci.yml`):
  - collector service: 26 tests
  - checkout limit Function: 6 tests
  - the product data validator
  - the store-setup dry run
  - Shopify **theme-check** (0 errors)
  - a full preview render
- **Visual checks:** every page was rendered from the real theme files with sample data and
  checked at desktop (1440px) and phone (390px) widths, with no sideways scrolling on
  phones.

### Not yet verified

These need a real store to test:

- AJAX cart and drawer calls (`/cart/add.js`, `/cart/change.js`)
- Search & Discovery filters
- Customer metafields read in Liquid
- The checkout Function inside Shopify checkout
- The Klaviyo client API
- App proxy signatures from real traffic
- The Admin API queries in the setup script and dashboard

The code follows Shopify's documented APIs. Expect small fixes during the first store
setup.

## 2. What's in the repo

| Path | What | Runs on |
|---|---|---|
| `theme/` | Shopify Online Store 2.0 theme (Liquid, CSS, vanilla JS, no build step) | Shopify |
| `scripts/` | `setup-store.mjs` creates all metafields, metaobjects and about 90 collections. `validate-catalogue.mjs` checks product CSVs before import | Your machine or CI (Node 20+) |
| `data/product-import-template.csv` | Product import template following the data and naming standard | — |
| `collector-service/` | Small Node service (no dependencies) behind a Shopify app proxy. It powers My Garage, profiles, wishlist sync, order webhooks, limit tracking and the **owner dashboard**. It stores all its data in Shopify | Any HTTPS host (Fly.io, Render, Railway) |
| `shopify-app/` | Shopify CLI app config (proxy, webhooks, scopes) plus the **purchase-limits** checkout Function | Shopify (`shopify app deploy`) |
| `preview/` | Renders the real theme with sample data into static pages and screenshots | Your machine or CI |
| `docs/` | Setup, operations, Phase 2, bundles and limits, screenshots | — |

## 3. Launch order

Each step links to its detailed doc.

1. **Shopify account.** Basic plan or higher. Set the currency to NZD with GST-inclusive
   prices, and turn on Shopify Payments with Apple Pay and Google Pay.
   ([setup §1](docs/setup.md))
2. **Theme.** `cd theme && shopify theme push --unpublished`. Upload the logo and set the
   menus. ([setup §2, §5](docs/setup.md))
3. **Data model.** Create an Admin API token, then run
   `node scripts/setup-store.mjs --dry-run`, then run it for real.
   ([setup §3](docs/setup.md))
4. **Search & Discovery.** Install the app and configure filters, searchable fields and
   synonyms. ([setup §4](docs/setup.md))
5. **Pages and blog.** Create the pages: drops, wishlist, brands, garage,
   collector-profile, shipping and pre-order policy. Create a blog with the handle
   `journal`. ([setup §4b, §6](docs/setup.md))
6. **Shipping.** NZ rates, free-shipping threshold, Auckland pickup, and Starshipit or
   NZ Post. ([setup §7](docs/setup.md))
7. **Products.** Fill the CSV template, run
   `node scripts/validate-catalogue.mjs products.csv --fix-tags > ready.csv`, then import.
   ([operations](docs/operations.md))
8. **Apps.**
   - Klaviyo
   - Google & YouTube, Facebook & Instagram
   - a reviews app
   - a pre-order deposit app, if you take deposits

   ([setup §8](docs/setup.md))
9. **Bundles discount.** Create the Buy X Get Y automatic discount that matches the theme
   setting. ([bundles-and-limits](docs/bundles-and-limits.md))
10. **Collector service and app** (optional for launch, needed for Phase 2, limits and the
    dashboard):
    - Deploy `collector-service/`.
    - Fill in `shopify-app/shopify.app.toml`, then run `shopify app deploy`.
    - Install the app.
    - Turn on the checkout rule.
    - Turn on *Collector features* in theme settings.

    See [collector-service/README](collector-service/README.md) and
    [phase-2](docs/phase-2.md).
11. **Before going live:** place test orders for in-stock, pre-order, mixed-cart, bundle
    and limited-release items. Check `/dashboard`. Go through the drop-day checklist.

## 4. Accounts and credentials needed

| Service | Used for | Where it is set |
|---|---|---|
| Shopify (store owner) | Everything | — |
| Shopify Dev Dashboard app | App proxy, webhooks, checkout Function, Admin API | `shopify-app/shopify.app.toml`; `SHOPIFY_API_KEY` and `SHOPIFY_API_SECRET` env vars on the service |
| Hosting for collector-service | Phase 2 and the dashboard | `SERVICE_URL`, `DASHBOARD_PASSWORD`, `DATA_DIR` volume |
| Klaviyo | Drop alerts, restock, reminders, interest sync | Public key in theme settings; `KLAVIYO_PRIVATE_KEY` on the service |

No credentials are committed. See `collector-service/.env.example`.

## 5. Decisions made, and why

- **Shopify, not a custom backend.** The SOP (§27) asks for it, and it gives you payments,
  hosting, backups and checkout.
- **Structured `scale.*` metafields** for scale, make, model, generation and the pre-order
  fields (§10, §12), so filters, collections and SEO all use the same data. The validator
  enforces the naming standard (§13).
- **One stock-state snippet** (`snippets/stock-state.liquid`) decides In stock, Low stock,
  Pre-order, Coming soon, Incoming, Sold out and Discontinued. An unavailable product can
  never show a buy button (§15).
- **Drops are `drop` metaobjects** with their own pages and an archive (§16).
- **Collector data lives in Shopify** (customer and product metafields, metaobjects), so the
  service is stateless.
- **Purchase limits are enforced at checkout** by a Shopify Function. The theme only
  explains the limits.
- **Bundle savings come from a native Shopify discount.** The theme only displays them.

## 6. Open items and decisions for the owner

- **The SOP text ended mid-sentence** at §42 ("Every design…"). Check whether anything
  after that was meant to be included.
- **Brand name, logo and tagline** are still working versions ("Scale Culture NZ",
  "Japanese automotive culture. In miniature.").
- **Fonts.** Barlow Condensed and Inter load from Google Fonts. Self-host them for speed and
  privacy (setup §10), or choose a licensed DIN-style font.
- **Pre-order deposits** need a selling-plan app such as PreProduct. Full-price pre-orders
  work without one.
- **Wishlist demand count.** It can drift by one under simultaneous saves. A nightly recount
  is optional.
- **"High views, low sales"** isn't in the owner dashboard, because the Admin API doesn't
  provide product views. Use Shopify's built-in report instead.
- **Real product photography** is needed: 3+ square images per product (§30). The preview
  uses placeholder graphics.

## 7. Day-to-day commands

```bash
# Theme
cd theme && shopify theme dev --store <store>.myshopify.com

# Products
node scripts/validate-catalogue.mjs products.csv --fix-tags > products.ready.csv

# Preview + screenshots (no store needed)
cd preview && npm install && npm run build && npm run screenshots

# Tests
cd collector-service && npm test
cd shopify-app/extensions/purchase-limits && npm test
```

Owner guides:
- [operations](docs/operations.md): adding stock, inventory workflow, drops, pre-orders,
  reporting.
- [bundles-and-limits](docs/bundles-and-limits.md): bundles, purchase limits and the
  drop-day checklist.

## 8. History

This project was built in the `skiptdouglas/lina` repository on the branch
`claude/scale-culture-nz-build-1pxz7s`, then moved here with its commit history. It has no
code dependency on Lina or JumpServer.
