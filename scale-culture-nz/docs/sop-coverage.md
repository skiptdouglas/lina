# SOP coverage

Status key:

- ✅ **Built**: implemented in this repository.
- ⚙️ **Config**: done in Shopify admin or an app, with steps in `setup.md`.
- 🔜 **Later**: Phase 2 or 3.

| § | Requirement | Status | Where |
|---|---|---|---|
| 2–3 | Brand, palette, typography, imagery | ✅ | `assets/base.css`, `layout/theme.liquid`, theme settings |
| 4 | Desktop nav and utility nav | ✅ | `sections/header.liquid` |
| 4 | Mobile nav: HOME, SHOP, DROPS, SEARCH, CART | ✅ | `snippets/mobile-nav.liquid` |
| 5 | Hero: STRAIGHT FROM JAPAN, two buttons | ✅ | `sections/hero.liquid` |
| 5 | New Arrivals cards: brand, name, scale, price, stock | ✅ | `sections/product-rail.liquid`, `snippets/product-card.liquid` |
| 6 | Shop by Scale, with 1:64 emphasised | ✅ | `sections/shop-by-scale.liquid` (first tile is the large one) |
| 7 | Die-cast, kit and accessory categories | ✅ / ⚙️ | `scripts/setup-store.mjs` collections |
| 8 | Brand pages: logo, description, new, available, pre-orders, sold out | ✅ | `templates/collection.brand.json`, `sections/brand-highlights.liquid` |
| 9 | Browse by vehicle manufacturer | ✅ | `<make>-models` collections and the manufacturer filter |
| 10 | Make → model → generation as structured data | ✅ | `scale.vehicle_make/model/generation`; hierarchy in `catalogue-schema.mjs` |
| 11 | Editorial collections | ✅ | `sections/editorial-collections.liquid`; 12 tag-driven collections |
| 12 | Product data standard | ✅ | `catalogue-schema.mjs`, `validate-catalogue.mjs`, `snippets/product-specs.liquid` |
| 13 | Naming standard | ✅ | Enforced by `validate-catalogue.mjs` |
| 14 | Product page layout, related, also bought, recently viewed | ✅ | `sections/main-product.liquid`, `product-recommendations`, `recently-viewed` |
| 15 | Seven stock states; unavailable is never purchasable | ✅ | `snippets/stock-state.liquid` |
| 16 | Drops: name, date, brands, count, grid, image, countdown, archive | ✅ | `drop` metaobject, `sections/main-drop.liquid`, `drops-index`, `featured-drop` |
| 17 | Pre-orders: dates, price, deposit, allocation, RESERVE YOURS, disclaimer | ✅ | `snippets/preorder-info.liquid` |
| 17 | Collecting a deposit at checkout | ⚙️ | Selling-plan app |
| 18 | Accounts: orders, shipping details, pre-orders, wishlist | ✅ | `templates/customers/*`, `sections/main-account.liquid` |
| 18 | Saved payment information | ⚙️ | Shop Pay |
| 19 | My Garage: owned / wanted / pre-ordered, totals by make, model collections | ✅ | `main-garage`, `garage-buttons`, collector service; auto-filled from orders |
| 20 | Wishlist on every product | ✅ | `snippets/wishlist-button.liquid`, `page.wishlist` (stored in the browser) |
| 20 | Wishlist demand reporting ("32 customers…") | ✅ | Synced wishlist + `scale.wishlist_count`, `snippets/wishlist-demand.liquid` |
| 21 | Drop Alerts with interests | ✅ | `sections/drop-alerts.liquid` → customer tags → Klaviyo |
| 22 | Search by name, make, model, brand, SKU, scale | ✅ / ⚙️ | `sections/main-search.liquid`, `--fix-tags`, Search & Discovery |
| 23 | Filters, working on mobile | ✅ / ⚙️ | `snippets/facets.liquid` (drawer on mobile); filter list set in Search & Discovery |
| 24 | Cart: image, name, scale, qty, price, shipping estimate, pre-order split | ✅ | `sections/main-cart.liquid` |
| 25 | Checkout: card, Apple Pay, Google Pay, minimal fields | ⚙️ | Shopify Payments; express buttons on the product page and cart |
| 26 | Shipping: NZ-wide, Auckland pickup, free threshold | ⚙️ / ✅ | Shipping settings; threshold progress bar in the cart |
| 27–28 | Shopify and integrations | ⚙️ | `setup.md` §1, §8 |
| 29 | Inventory workflow | ✅ | `availability` field states; validator guards; `operations.md` |
| 30 | Image standard | ✅ | Square crops in the grid; validator checks count and ALT text |
| 31 | Mobile-first, sticky add to cart, buy in about 4 taps | ✅ | Sticky ATC above the tab bar, quick add on cards, slide-out cart, Apple Pay on the product page |
| 32 | SEO: unique titles and descriptions, structured data, ALT text | ✅ | `snippets/meta-tags.liquid` (JSON-LD), validator |
| 33 | Journal, with articles linking to products | ✅ | `templates/blog.json`, `article.json`, `sections/main-article.liquid` (Shop this story), `journal-rail` |
| 34–35 | Analytics and admin dashboard | ✅ / ⚙️ | Owner dashboard (`collector-service/src/dashboard.js`); Shopify reports for views/conversion (`operations.md`) |
| 36 | Phase 1 MVP | ✅ | Everything above |
| 37 | Collector profiles | ✅ | `collector-profile-form`, public `collector` metaobject pages |
| 37 | Advanced wishlist (synced across devices) | ✅ | Collector service `/wishlist` |
| 37 | Interest-based notifications | ✅ / ⚙️ | Interests → Klaviyo profile properties; segments in `phase-2.md` |
| 37 | Restock alerts | ✅ / ⚙️ | `snippets/restock-form.liquid` → Klaviyo Back in Stock |
| 37 | Advanced drop alerts (per-drop reminders) | ✅ / ⚙️ | `snippets/drop-reminder.liquid` → Klaviyo event |
| 37 | Collection recommendations | ✅ | `sections/recommended-for-you.liquid` |
| 37 | Customer reviews | ✅ / ⚙️ | `product-reviews` section (app block), `snippets/rating.liquid`, stars on cards |
| — | Bundles (product page + cart suggestion) | ✅ / ⚙️ | `sections/product-bundle.liquid`, cart drawer suggestion; Buy X Get Y discount in admin |
| — | Drop-day purchase limits | ✅ / ⚙️ | `shopify-app/extensions/purchase-limits` (checkout Function), collector-service limit tracking, theme limit note |
| 38 | Phase 3 | 🔜 | |
| 39 | Performance | ✅ | Responsive images, lazy loading, no framework, no autoplay |
| 40–42 | Catalogue mix and positioning | — | Business guidance; the editorial and brand sections are built to show off a curated range |
