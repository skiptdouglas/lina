# Phase 2: collector features (SOP §37)

| Feature | What the collector sees | How it works |
|---|---|---|
| **My Garage** (§19) | Owned / Wanted / Pre-ordered buttons on every product. A garage page with "Models owned: 84", a breakdown by manufacturer, status tabs and model collections such as "Nissan Skyline R34 — 5" | `snippets/garage-buttons.liquid`, `sections/main-garage.liquid`; data is stored by the collector service |
| Auto-garage | Buying a pre-order adds it as *Pre-ordered*. Once fulfilled, every item becomes *Owned*. The collector can switch this off in their profile | `orders/create` and `orders/fulfilled` webhooks; statuses only ever move up (wanted → pre-ordered → owned) |
| **Collector profiles** | Display name, location, bio and interests. Optionally a public page at `/pages/collector/<name>` showing owned models (and wanted, if chosen) | `sections/collector-profile-form.liquid` → `collector` metaobject → `sections/main-collector.liquid` |
| **Advanced wishlist** | The wishlist follows a logged-in collector across devices. Sold-out pages show "32 collectors have this on their wishlist" | The service syncs it to the account and keeps `scale.wishlist_count` up to date. The threshold is a theme setting |
| **Restock alerts** | A "Notify me" email form on sold-out, coming-soon and incoming products | Klaviyo Back in Stock subscription (client API, public key only) |
| **Advanced drop alerts** | A "Remind me" form on upcoming drop pages | Klaviyo event `Drop Reminder Requested` with the drop name, date, brands and URL |
| **Interest-based notifications** | Emails only about the makes, scales and brands they collect | Profile interests and garage makes are copied to Klaviyo profile properties (`sc_interest_makes`, `sc_garage_top_makes`, and so on) |
| **Collection recommendations** | "Complete your Nissan Skyline R34 collection" and "Recommended for you" on the home page, garage page and account page | `sections/recommended-for-you.liquid`. It uses garage collections, top makes and interests, and leaves out anything they already have |
| **Customer reviews** | Star ratings on cards and product pages, and a reviews section | Any reviews app that writes Shopify's standard `reviews.rating` metafields; its app block goes in the *Reviews* section |

## Turning it on

1. Deploy the collector service. See `collector-service/README.md`.
2. Re-run `node scripts/setup-store.mjs`. It adds the customer metafields, the
   `scale.wishlist_count` product field and the `collector` metaobject. Existing items are
   skipped.
3. Create these pages:

   | Page | Handle | Template |
   |---|---|---|
   | My Garage | `garage` | `page.garage` |
   | Collector profile | `collector-profile` | `page.collector-profile` |

4. Theme settings → **Collector features (Phase 2)**:
   - Turn on *Enable My Garage…*.
   - Set the proxy path, which defaults to `/apps/collector`.
   - Set the wishlist demand threshold.
   - Add the **Klaviyo public key**.
5. Install a reviews app (Judge.me or Shopify Product Reviews). Then add its block in Theme
   editor → Product → *Reviews*.

## Klaviyo setup

**Restock alerts**
- Turn on *Back in Stock* in the Klaviyo Shopify integration.
- Set up the built-in "Back in Stock" flow. It sends when inventory comes back.

**Drop reminders**
- Create a flow triggered by the metric *Drop Reminder Requested*. Its first email
  confirms the reminder.
- On drop day, send a campaign to the segment *"What someone has done: Drop Reminder
  Requested where drop_handle = japan-drop-005, at least once, over all time"*.

**Interest segments** (for new-arrival and drop campaigns)
- *Nissan collectors*: `sc_interest_makes` contains "Nissan" **or** `sc_garage_top_makes`
  contains "Nissan".
- *1:64 collectors*: `sc_interest_scales` contains "1:64" **or** `sc_garage_top_scale` =
  "1:64".
- *INNO64 fans*: `sc_interest_brands` contains "INNO64".
- *Big collectors* (for VIP early access later, §38): `sc_garage_owned` ≥ 50.

**Wishlist price drops**
- `sc_wishlist` holds product handles. Pair it with Klaviyo's *Price Drop* flow.

The Drop Alerts newsletter signup still records interests as customer tags
(`interest:make:nissan`), so guests can be segmented without an account.

## Using the data

- **Reorder decisions** (§20): Products → filter by *Wishlist demand* (the field is pinned),
  or export products and sort by `scale.wishlist_count`. A sold-out model with a high count
  is a reorder candidate.
- **Demand by make**: garage stats are on each customer. In Klaviyo, the size of each
  interest segment is a quick read on demand.
