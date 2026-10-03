# Theme preview

This folder renders the real theme into static HTML pages and screenshots, so you can review
the design without a Shopify store. It uses the actual layout, JSON templates, sections,
snippets, locales and CSS. Sample products, collections, a drop, journal articles and a
collector's garage stand in for store data (`sample-data.mjs`).

```bash
npm install
npm run build          # → dist/*.html (open dist/index.html in a browser)
npm run screenshots    # → ../docs/screenshots/*.jpg (desktop 1440px + mobile 390px)
```

`build.mjs` imitates the Shopify-only parts with LiquidJS, just closely enough to render:
the `form`, `paginate`, `section` and `sections` tags, and the `t`, `money`, `image_url`
and `image_tag` filters, among others. A page that renders here can still differ on
Shopify where a shim simplifies. Pagination, filtering and cart calls need a real store.

Two differences from the live site:
- **Fonts.** Barlow Condensed and Inter come from Google Fonts. Without network access the
  headings fall back to Arial, so they look wider than they will in production.
- **Images.** The car pictures are generated placeholders. Real product photography goes in
  through Shopify.

Pages:
- `index`
- `product` (in stock), `product-preorder`, `product-sold-out` (shows the wishlist demand
  line and the restock form)
- `collection` (with filters)
- `cart`
- `journal` and `article`
- `drop`
- `garage` (logged-in collector)
- `dashboard` (owner dashboard with sample orders)
