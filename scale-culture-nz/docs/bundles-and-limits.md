# Bundles and drop-day purchase limits

## Bundles

| Where | What the customer sees |
|---|---|
| Product page, **Complete the display** | The model plus up to 3 add-ons, such as display cases, stands, dioramas or paint. Each add-on has a checkbox. A live bundle total shows the saving. **Add bundle to cart** adds everything in one step and opens the cart. |
| Slide-out cart, **Complete the display** | Suggests one display case when the cart has no item from that collection yet, with a one-tap **+ Add**. |

### How to set it up

1. **Choose the add-ons for each product.** Fill in **Bundle with** (`scale.bundle_products`)
   on the product, for example an INNO64 R34 → the 1:64 acrylic case and the garage diorama.
   Products without it fall back to the **Default add-ons** collection in theme settings.
2. **Set the theme settings** (Theme settings → Bundles):
   - Bundle discount: for example 15%.
   - Discounted add-on collection: for example *Display Cases*.
   - Cart suggestion collection: for example *Display Cases*.
3. **Create the matching discount in Shopify.** The theme only *shows* the saving; Shopify
   applies it at checkout.
   - Go to Discounts → Create discount → **Buy X get Y** → Automatic discount.
   - Customer buys: minimum quantity 1, from collections *Die-Cast* and *Plastic Model Kits*.
   - Customer gets: any quantity from *Display Cases*, at **15%** off (the same percentage
     as the theme setting).
   - Leave "maximum number of uses per order" blank if you want every case discounted.
     Otherwise set it to 1, and note that the bundle total on the product page will then
     overstate the saving for extra cases.

   If the theme setting and the discount don't match, the product page and checkout will
   show different prices. Change both together.
4. **Fixed bundles (optional).** For set products such as a "Kit starter pack" (Aoshima kit +
   paint + glue at a set price), use Shopify's free **Shopify Bundles** app. Its bundles
   are normal products to the theme and keep inventory in sync for each component.

Bundle lines carry a hidden `_bundle` property (the product handle). This lets you report
on bundle sales: export the orders and filter on the line property.

## Drop-day purchase limits

Limits stop one buyer taking a whole allocation on drop day. Three parts work together:

| Layer | Role |
|---|---|
| **Checkout Function** (`shopify-app/extensions/purchase-limits`) | **Enforces** the limit. Shopify checkout blocks any order over the limit, including bots that skip the storefront. |
| **Collector service** (`orders/create`, `orders/cancelled` webhooks) | Keeps each logged-in customer's running count (`scale.limited_purchases`), so the limit holds across separate orders. Cancelled orders give the allowance back. Retried webhooks are counted once. |
| **Theme** | Shows the rule up front: a "Limited release · Max 2 per customer" note, and "You can buy 1 more" for customers who have already bought. Quantity is capped, quick add is hidden once the limit is reached, and a friendly message appears before an over-limit add. |

### Setting a limit on a product

| Field | Example | Meaning |
|---|---|---|
| **Limit per customer** (`scale.max_per_customer`) | `2` | Units per customer across all their orders |
| **Limit applies until** (`scale.limit_until`) | `2026-10-20` | Last day of the limit (inclusive, NZ date). Leave it blank to keep the limit on |
| **Limited: require login** (`scale.limit_requires_login`) | ✓ | Guests must log in. Without login, the limit can only count the current cart |

Once the date passes, the product sells normally again with no other change needed.

### Deploying the Function (one-off)

```bash
npm i -g @shopify/cli
cd shopify-app            # set client_id and URLs in shopify.app.toml first
shopify app deploy        # builds the Function to WebAssembly and releases it
```

Then go to Settings → Checkout → **Checkout rules** → Add rule → *Drop purchase limits* →
Save and turn it on. Tests for the rule logic: `cd extensions/purchase-limits && npm test`.

### Drop-day checklist

- [ ] Set the limit and the "until" date on every product in the drop.
- [ ] For the hottest models, require login.
- [ ] Turn on bot protection: Online Store → Preferences → **Spam protection** → enable
      hCaptcha on login, create-account and contact forms.
- [ ] Test the limit with a staff account before the drop goes live.
- [ ] After the drop, check the dashboard's sell-through for the drop.
