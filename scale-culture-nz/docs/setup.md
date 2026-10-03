# Launch setup checklist

Work through this list top to bottom. Each item points to the SOP section it satisfies.

## 1. Shopify store (§27)

- [ ] Shopify **Basic** plan or higher, with the store currency set to **NZD** and prices
      entered including GST (Settings → Taxes: "Include tax in prices").
- [ ] **Shopify Payments** (§25): turn on credit/debit cards, **Apple Pay** and **Google Pay**.
      **Shop Pay** is optional. PayPal and Afterpay can be added later.
- [ ] Checkout (§25): Settings → Checkout → customer contact **email**, company name **hidden**,
      address line 2 **optional**, phone **optional**. This keeps checkout to the minimum.
- [ ] Customer accounts (§18): either *Classic* accounts (this theme ships the login, register
      and account templates, including a "My pre-orders" panel) or *New customer accounts*
      (Shopify hosts the pages). Classic is recommended for Phase 1 because it keeps the
      pre-order panel.
- [ ] Domain with HTTPS: automatic on Shopify (§39). Backups: install **Rewind** or a similar
      backup app (§39).

## 2. Theme

```bash
cd theme
shopify theme push --unpublished
```

Then go to Online Store → Themes → Customize:

- Header: upload the logo and pick the `main-menu` menu.
- Theme settings: low-stock threshold (3), free-shipping threshold ($150), shipping and
  pre-order copy.
- Home page: point **Featured drop** at the current drop, and check the collection blocks.

## 3. Data model and collections

```bash
node scripts/setup-store.mjs     # see README for env vars
```

This script creates the following:

- **Product metafields** in the `scale.*` namespace: scale, vehicle make, model and
  generation, availability, colour, year, series, motorsport category, street/race, release
  date, country, limited edition, MPN, package dimensions, the pre-order fields, and a drop
  reference.
- **Collection metafield** `scale.brand_logo`.
- **Metaobject** `drop`, published to the web at `/pages/drop/<handle>`.
- **Smart collections**, with handles matching the theme:
  - new-arrivals, pre-orders, sale, die-cast, model-kits, accessories
  - the scale collections: 1-64-diecast, 1-43-diecast, 1-24, 1-18-diecast, other-scales-diecast
  - one per kit and accessory category (by tag)
  - 13 brand collections, which use the `brand` template
  - one per vehicle manufacturer (`nissan-models` and so on)
  - 12 editorial collections (JDM Legends, 90s Japan and the rest, by `collection:<handle>` tag)

After the script runs:

- [ ] Online Store → Themes → Customize → Drop metaobject template: check it uses `drop`.
- [ ] Upload a logo to each brand collection's **Brand logo** metafield, and add a short
      description (§8).

## 4. Search and filters (§22, §23)

Install **Shopify Search & Discovery**, which is free and made by Shopify.

- [ ] **Filters**, in this order: Availability, Product type, Price, Vendor (shown as
      "Brand"), Scale, Vehicle manufacturer, Vehicle model, Vehicle generation, Availability
      override (shown as "Release status"), Motorsport category, Street / Race,
      Country of origin, Limited edition.
      - New release is covered by the `new-arrivals` collection and the sort order.
      - Pre-order is covered by the "Release status" filter.
- [ ] **Search**: add the product metafields `scale.vehicle_make`, `scale.vehicle_model` and
      `scale.vehicle_generation` as searchable fields if your plan supports it. Either way,
      run `validate-catalogue.mjs --fix-tags`, which also copies these values into product
      tags, and tags are always searchable.
- [ ] **Synonyms**: `R34 = Skyline R34 = BNR34`, `Supra = A80 = JZA80`, `FD = FD3S = RX-7`,
      `LBWK = Liberty Walk`, `TLV = Tomica Limited Vintage`, `Evo = Lancer Evolution`.
- [ ] **Complementary products** (shown as "Customers also bought"): pair display cases with
      1:64 cars, and paint with kits.

## 4b. Journal (§33)

- [ ] Online Store → Blog posts → Manage blogs → create a blog with the handle `journal`.
- [ ] Footer menu `footer-journal`: link the Journal and its tags, such as Collector guides,
      Brand guides, Build guides and New releases.
- [ ] On each article, fill in **Shop this story** (`scale.products`) with the models it
      mentions.

## 5. Navigation (§4)

Online Store → Navigation:

- `main-menu`: New → /collections/new-arrivals, Die-Cast → /collections/die-cast (with a
  scale sub-menu), Model Kits → /collections/model-kits, Pre-Orders →
  /collections/pre-orders, Brands → /pages/brands, Drops → /pages/drops, Sale →
  /collections/sale.
- Footer menus: `footer-shop`, `footer-brands`, `footer-help` (Shipping, Pre-order policy,
  Returns, Contact) and `footer-journal`.

## 6. Pages

| Page | Template | Purpose |
|---|---|---|
| Drops | `page.drops` | Drop archive (§16) |
| Wishlist | `page.wishlist` | Wishlist (§20), at handle `wishlist` |
| Brands | `page.brands` | Brand index (§8) |
| Shipping | `page` | Costs, free threshold, delivery times, tracking, pre-order rules (§26) |
| Pre-order policy | `page` | Dates may change, deposits, cancellations (§17) |

## 7. Shipping (§26)

Settings → Shipping and delivery:

- **New Zealand** zone:
  - Standard tracked courier, $7.50
  - Rural delivery, +$5
  - Free over $150 (keep this in step with the theme setting)
- **Local pickup**: turn on for the Auckland location.
- **Courier integration**: **Starshipit** or **NZ Post eShip** for labels and tracking
  emails. Both connect to NZ Post, CourierPost and NZ Couriers.
- **Pre-orders**: pre-order lines carry the `_preorder` property. Use Starshipit rules (or
  hold the fulfilment) so mixed orders ship the in-stock items first.

## 8. Apps and integrations (§17, §20, §21, §28)

| Need | App | Notes |
|---|---|---|
| Pre-order **deposits** / partial payment | **PreProduct** or Shopify's **Pre-order** selling plans | Deposits need a selling-plan app; the theme only *displays* the deposit. Full-price pre-orders work without an app. |
| Email + Drop Alerts | **Klaviyo** | Turn on the Shopify integration. The newsletter form saves customer tags like `interest:make:nissan`, `interest:type:1-64` and `interest:brand:inno64`, which Klaviyo syncs, so you can build segments from them. |
| Restock / back-in-stock alerts (Phase 2) | Klaviyo Back in Stock | Turn on when ready. |
| Wishlist demand reporting | Built in (Phase 2) | Phase 1 keeps wishlists in the browser. The Phase 2 collector service syncs them to customer accounts and maintains the "32 collectors want this" count (§20). See `phase-2.md`. |
| Google Analytics 4 + Merchant Centre | **Google & YouTube** channel | Product feed uses the SEO title/description, GTIN (barcode), MPN and brand. |
| Meta Pixel, Facebook, Instagram Shopping | **Facebook & Instagram** channel | Turn on Conversions API. |
| Reviews (Phase 2) | Judge.me or Shopify Product Reviews | Add its block to the product *Reviews* section. Stars come from the standard `reviews.rating` metafields. |

## 9. SEO (§32)

- Every product needs a unique SEO title and description. The validator enforces both.
- Collection descriptions should target the searches from the SOP, for example
  `1-64-diecast` → "1:64 diecast NZ", `jdm-legends` → "JDM diecast NZ".
- `snippets/meta-tags.liquid` outputs Product JSON-LD with brand, SKU, GTIN, MPN, scale,
  vehicle make and model, and the availability (pre-order, discontinued, out of stock).
- Submit the sitemap at `/sitemap.xml` in Google Search Console.

## 10. Performance (§39)

- Images use Shopify's CDN with responsive `srcset`, lazy loading below the fold, and
  `fetchpriority=high` on the hero.
- There is no JavaScript framework. `theme.js` is around 8 KB unminified, and there is no
  autoplay video.
- Google Fonts is the one third-party asset. To remove it, self-host Barlow Condensed and
  Inter in `assets/` and swap the `<link>` in `layout/theme.liquid` for `@font-face` rules.
