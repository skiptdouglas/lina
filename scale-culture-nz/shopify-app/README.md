# Shopify app

This is the Shopify CLI app configuration for Scale Culture NZ. One custom app holds:

- **App proxy and webhooks** for the [collector service](../collector-service)
  (`/apps/collector`, plus the order and privacy webhooks).
- **`extensions/purchase-limits`**: a cart and checkout validation Function
  (`cart.validations.generate.run`) that enforces drop-day purchase limits.

Read [`../docs/bundles-and-limits.md`](../docs/bundles-and-limits.md) for setup and the
drop-day checklist.

```bash
cd extensions/purchase-limits && npm test   # rule logic (node:test)
cd ../.. && shopify app deploy              # build + release (needs Shopify CLI and the app's client_id)
```

The Function's input query reads product metafields `scale.max_per_customer`,
`scale.limit_until` and `scale.limit_requires_login`, and the customer metafield
`scale.limited_purchases`. If Shopify changes the Function API, run
`shopify app function typegen` and check the input against
`src/cart_validations_generate_run.graphql`.
