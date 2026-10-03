# Running the store

This is the owner's day-to-day guide.

## Adding a product (§12, §13, §30)

1. Copy a row from `data/product-import-template.csv`. For one product you can also use
   Shopify Admin directly: every `scale.*` field is pinned at the bottom of the product page.
2. Write the **title** as `Brand – Vehicle – Variant – Scale`, for example
   `INNO64 – Nissan Skyline GT-R R34 V-Spec – Midnight Purple – 1:64`.
   Never use something vague like "Purple Skyline".
3. Set **Card title** to the short vehicle name shown on product cards, for example
   `Nissan Skyline GT-R R34 V-Spec`.
4. Fill in the required fields:
   - SKU, brand (Vendor) and price
   - Type: `Die-cast`, `Plastic Model Kit` or `Accessory`
   - Scale
   - Vehicle manufacturer, model and generation
   - Availability
5. Add the tags that place the product in collections:
   - Editorial collections: `collection:jdm-legends`, `collection:super-gt`, and so on.
   - Kits: `kit:japanese-cars`, `kit:tuner-cars`, and so on.
   - Accessories: `accessory:display-cases`, and so on.
6. Images: at least 3, all square and the same size (2048×2048 recommended). Use a
   front three-quarter shot first, then the rear, then the packaging. Every image needs ALT
   text.
7. SEO title (70 characters or fewer) and SEO description (160 characters or fewer), both
   unique.
8. Run the validator before every import:

   ```bash
   node scripts/validate-catalogue.mjs products.csv --fix-tags > products.ready.csv
   ```

## Inventory workflow (§29)

The **Availability override** field (`scale.availability`) follows the stock from the
supplier order to the shelf:

| Stage | Availability | Inventory qty | Status | Shop shows |
|---|---|---|---|---|
| Supplier order placed, PO entered | `coming_soon` | 0 | Active (or Draft until it's announced) | COMING SOON, no buy button |
| Shipment dispatched | `incoming` | 0 | Active | INCOMING, no buy button |
| Shipment received, **quantity verified** | `auto` | counted qty | Active | IN STOCK / LOW STOCK |
| Drop launched | `auto` | — | Active, linked to the Drop | Product appears in the drop grid |
| Sold through | `auto` | 0 | Active | SOLD OUT (keep the page for SEO and wishlist demand) |
| Won't be restocked | `discontinued` | 0 | Active | DISCONTINUED |

Rules:

- **Never** enter a quantity before the stock has been counted. The validator flags
  `coming_soon` or `incoming` products that have a quantity.
- **Pre-orders** are the only exception. Set availability to `preorder`, inventory policy to
  "Continue selling when out of stock", and quantity to the allocation you've secured. When
  the allocation runs out, the product shows SOLD OUT automatically.
- When pre-order stock lands, switch availability to `auto`, set the inventory policy back to
  "deny", and enter the counted quantity.

Shopify **Purchase orders** (Products → Purchase orders, made by Shopify) track supplier
orders and add the quantity to inventory when you mark them received.

## Launching a drop (§16)

1. Create a collection for the drop, for example a manual collection `japan-drop-004`, and
   add its products.
2. Go to Content → Metaobjects → Drop → Add entry and fill in:
   - **Name**: "Japan Drop #004"
   - **Number**: 4
   - **Release date**: 18 October 2026, 7:00 pm
   - **Brands**: INNO64, POP RACE, AOSHIMA
   - **Image** and **summary**
   - **Collection**: the one from step 1
3. Set the status to **Active**. This publishes the page at `/pages/drop/japan-drop-004`.
4. In the theme editor, point **Home → Featured drop** at the new drop. Its countdown runs
   until the release time.
5. Optionally set each product's **Drop** field, which makes drop reports easier.
6. In Klaviyo, send to the segment of customers whose `interest:*` tags match the drop's
   brands, makes and scales.

Past drops stay listed at `/pages/drops`.

## Pre-orders (§17)

Each pre-order product needs these fields:

- Expected Japanese release, for example "November 2026"
- Expected NZ arrival, for example "December 2026"
- Deposit, for example "$10" (leave it blank if the customer pays in full)
- Total allocation

The product page shows these fields together with the "dates may change" disclaimer (Theme
settings → Pre-orders). Charging a deposit at checkout needs a selling-plan app (see
`setup.md` §8).

## Daily dashboard (§35)

The **owner dashboard** at `<collector service>/dashboard` shows everything below on one
page (see `collector-service/README.md`). The table lists where each number lives in
Shopify, if you want to dig deeper.

| Question | Where |
|---|---|
| Today's sales | Shopify Home / Analytics |
| Orders awaiting fulfilment | Orders → filter *Unfulfilled* |
| Low-stock products | Products → Inventory, sorted by *Available* (or the Stocky app) |
| Incoming stock | Products → Purchase orders → *Ordered* |
| Open pre-orders | Orders → search `_preorder` / tag rule in Starshipit |
| Best-selling models / brands | Analytics → Reports → *Sales by product* / *Sales by vendor* |
| High views, low sales | Analytics → Reports → *Product views and conversion* |
| Wishlist demand | Wishlist app dashboard (once installed) |

Useful ShopifyQL queries (Analytics → Reports → New exploration):

```sql
-- Revenue by brand (§34)
FROM sales SHOW net_sales, quantity_ordered GROUP BY product_vendor SINCE -30d ORDER BY net_sales DESC

-- Revenue by scale / vehicle manufacturer (requires metafields as report dimensions,
-- otherwise group by product tag)
FROM sales SHOW net_sales GROUP BY product_tags SINCE -30d ORDER BY net_sales DESC

-- Search terms (§34)
FROM searches SHOW searches, search_conversions GROUP BY search_query SINCE -30d
```

**Sell-through per drop** (§34): for each drop collection, sell-through = units sold in the
first 7 days ÷ units received. For example, Japan Drop #004 had 47 SKUs and 280 units
received, and 72% sold within 7 days. Export the "Sales by product" report filtered to the
drop's products and compare it with the received quantities from the purchase order.
