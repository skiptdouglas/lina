#!/usr/bin/env node
// One-off store bootstrap for Scale Culture NZ via the Shopify Admin GraphQL API.
// Creates: the `drop` and `collector` metaobjects, customer metafields (Phase 2), product + collection metafield definitions
// (storefront-readable, filterable, pinned), and the smart collections the theme
// links to (scales, categories, brands, makes, editorial, pre-orders, new, sale).
//
// Safe to re-run: anything that already exists is skipped.
//
//   SHOPIFY_STORE=scaleculture.myshopify.com SHOPIFY_ADMIN_TOKEN=shpat_... node setup-store.mjs
//   node setup-store.mjs --dry-run      # print the plan, no API calls
//
// Token scopes: write_products, write_metaobject_definitions, write_metaobjects, write_publications

import {
  NAMESPACE, PRODUCT_METAFIELDS, COLLECTION_METAFIELDS, CUSTOMER_METAFIELDS, DROP_METAOBJECT, COLLECTOR_METAOBJECT, BRANDS, EDITORIAL_COLLECTIONS,
  KIT_CATEGORIES, ACCESSORY_CATEGORIES, VEHICLE_MAKES, handleize
} from './catalogue-schema.mjs';

const DRY_RUN = process.argv.includes('--dry-run');
const STORE = process.env.SHOPIFY_STORE;
const TOKEN = process.env.SHOPIFY_ADMIN_TOKEN;
const API_VERSION = process.env.SHOPIFY_API_VERSION || '2025-10';

if (!DRY_RUN && (!STORE || !TOKEN)) {
  console.error('Set SHOPIFY_STORE and SHOPIFY_ADMIN_TOKEN, or pass --dry-run.');
  process.exit(1);
}

async function gql(query, variables = {}) {
  const res = await fetch(`https://${STORE}/admin/api/${API_VERSION}/graphql.json`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Shopify-Access-Token': TOKEN },
    body: JSON.stringify({ query, variables })
  });
  const body = await res.json();
  if (!res.ok || body.errors) throw new Error(JSON.stringify(body.errors || body, null, 2));
  return body.data;
}

const isAlreadyExists = (errors) =>
  errors.some((e) => /taken|already exists|in use/i.test(e.message) || e.code === 'TAKEN');

function report(label, errors) {
  if (!errors.length) return console.log(`  ✓ ${label}`);
  if (isAlreadyExists(errors)) return console.log(`  · ${label} (exists)`);
  console.log(`  ✗ ${label}: ${errors.map((e) => e.message).join('; ')}`);
}

function validationsFor(def, metaobjectIds = {}) {
  const v = [];
  if (def.choices) v.push({ name: 'choices', value: JSON.stringify(def.choices) });
  if (def.metaobject) v.push({ name: 'metaobject_definition_id', value: metaobjectIds[def.metaobject] });
  if (def.fileTypes) v.push({ name: 'file_type_options', value: JSON.stringify(def.fileTypes) });
  return v;
}

async function createMetaobject(def) {
  console.log(`\nMetaobject: ${def.type}`);
  if (DRY_RUN) return `gid://dry-run/MetaobjectDefinition/${def.type}`;
  const existing = await gql(`query($t: String!) { metaobjectDefinitionByType(type: $t) { id } }`, { t: def.type });
  if (existing.metaobjectDefinitionByType) {
    console.log(`  · ${def.type} (exists)`);
    return existing.metaobjectDefinitionByType.id;
  }
  const data = await gql(
    `mutation($d: MetaobjectDefinitionCreateInput!) {
      metaobjectDefinitionCreate(definition: $d) { metaobjectDefinition { id } userErrors { message code } }
    }`,
    {
      d: {
        type: def.type,
        name: def.name,
        displayNameKey: def.displayNameKey,
        access: { storefront: 'PUBLIC_READ' },
        capabilities: {
          publishable: { enabled: true },
          onlineStore: { enabled: true, data: { urlHandle: def.urlHandle } }
        },
        fieldDefinitions: def.fields.map((f) => ({ key: f.key, name: f.name, type: f.type, required: !!f.required }))
      }
    }
  );
  const r = data.metaobjectDefinitionCreate;
  report(def.type, r.userErrors);
  return r.metaobjectDefinition?.id;
}

async function createMetafields(ownerType, defs, metaobjectIds) {
  console.log(`\nMetafield definitions (${ownerType})`);
  const ids = {};
  for (const def of defs) {
    const input = {
      namespace: NAMESPACE,
      key: def.key,
      name: def.name,
      description: def.description,
      type: def.type,
      ownerType,
      pin: true,
      access: ownerType === 'CUSTOMER' ? undefined : { storefront: 'PUBLIC_READ' },
      validations: validationsFor(def, metaobjectIds),
      capabilities: def.filter ? { smartCollectionCondition: { enabled: true }, adminFilterable: { enabled: true } } : undefined
    };
    if (DRY_RUN) {
      console.log(`  ${NAMESPACE}.${def.key} (${def.type})${def.choices ? ` choices: ${def.choices.length}` : ''}${def.filter ? ' [filter]' : ''}`);
      ids[def.key] = `gid://dry-run/MetafieldDefinition/${def.key}`;
      continue;
    }
    const data = await gql(
      `mutation($d: MetafieldDefinitionInput!) {
        metafieldDefinitionCreate(definition: $d) { createdDefinition { id } userErrors { message code } }
      }`,
      { d: input }
    );
    const r = data.metafieldDefinitionCreate;
    report(`${NAMESPACE}.${def.key}`, r.userErrors);
    ids[def.key] = r.createdDefinition?.id;
  }
  if (!DRY_RUN) {
    // Look up ids for definitions that already existed
    const data = await gql(
      `query($o: MetafieldOwnerType!, $n: String!) { metafieldDefinitions(first: 100, ownerType: $o, namespace: $n) { nodes { id key } } }`,
      { o: ownerType, n: NAMESPACE }
    );
    for (const n of data.metafieldDefinitions.nodes) ids[n.key] = ids[n.key] || n.id;
  }
  return ids;
}

function collectionPlan(mf) {
  const metafieldRule = (key, value) => ({
    column: 'PRODUCT_METAFIELD_DEFINITION', relation: 'EQUALS', condition: value, conditionObjectId: mf[key]
  });
  const type = (t) => ({ column: 'TYPE', relation: 'EQUALS', condition: t });
  const tag = (t) => ({ column: 'TAG', relation: 'EQUALS', condition: t });
  const c = (title, handle, rules, extra = {}) => ({ title, handle, rules, ...extra });

  return [
    // Navigation
    c('New Arrivals', 'new-arrivals', [{ column: 'VARIANT_PRICE', relation: 'GREATER_THAN', condition: '0' }], { sortOrder: 'CREATED_DESC' }),
    c('Pre-Orders', 'pre-orders', [metafieldRule('availability', 'preorder')], { templateSuffix: 'preorders', sortOrder: 'CREATED_DESC' }),
    c('Sale', 'sale', [{ column: 'IS_PRICE_REDUCED', relation: 'IS_SET', condition: '' }]),
    c('Die-Cast', 'die-cast', [type('Die-cast')], { sortOrder: 'CREATED_DESC' }),
    c('Plastic Model Kits', 'model-kits', [type('Plastic Model Kit')], { sortOrder: 'CREATED_DESC' }),
    c('Accessories', 'accessories', [type('Accessory')]),
    // Die-cast by scale (SOP §6–7)
    c('1:64 Die-Cast', '1-64-diecast', [type('Die-cast'), metafieldRule('scale', '1:64')], { sortOrder: 'CREATED_DESC' }),
    c('1:43 Die-Cast', '1-43-diecast', [type('Die-cast'), metafieldRule('scale', '1:43')], { sortOrder: 'CREATED_DESC' }),
    c('1:24 Die-Cast & Kits', '1-24', [metafieldRule('scale', '1:24')], { sortOrder: 'CREATED_DESC' }),
    c('1:18 Die-Cast', '1-18-diecast', [type('Die-cast'), metafieldRule('scale', '1:18')], { sortOrder: 'CREATED_DESC' }),
    c('Other Scale Die-Cast', 'other-scales-diecast', [type('Die-cast'), metafieldRule('scale', 'Other')], { sortOrder: 'CREATED_DESC' }),
    // Model kit + accessory categories, driven by tags (kit:japanese-cars, accessory:display-cases)
    ...KIT_CATEGORIES.map((k) => c(`${k} Kits`, `kits-${handleize(k)}`, [type('Plastic Model Kit'), tag(`kit:${handleize(k)}`)])),
    ...ACCESSORY_CATEGORIES.map((a) => c(a, handleize(a), [type('Accessory'), tag(`accessory:${handleize(a)}`)])),
    // Brands (SOP §8) — use the brand template
    ...BRANDS.map((b) => c(b, handleize(b), [{ column: 'VENDOR', relation: 'EQUALS', condition: b }], { templateSuffix: 'brand', sortOrder: 'CREATED_DESC' })),
    // Vehicle manufacturers (SOP §9)
    ...VEHICLE_MAKES.filter((m) => m !== 'Other').map((m) => c(`${m} Models`, `${handleize(m)}-models`, [metafieldRule('vehicle_make', m)], { sortOrder: 'CREATED_DESC' })),
    // Editorial (SOP §11) — tag products with collection:<handle>
    ...EDITORIAL_COLLECTIONS.map((e) => c(e, handleize(e), [tag(`collection:${handleize(e)}`)], { sortOrder: 'CREATED_DESC' }))
  ];
}

async function onlineStorePublicationId() {
  const data = await gql(`{ publications(first: 20) { nodes { id name } } }`);
  return data.publications.nodes.find((p) => p.name === 'Online Store')?.id;
}

async function createCollections(mf) {
  const plan = collectionPlan(mf);
  console.log(`\nSmart collections (${plan.length})`);
  const publicationId = DRY_RUN ? null : await onlineStorePublicationId();
  for (const col of plan) {
    if (DRY_RUN) {
      console.log(`  /collections/${col.handle}  ←  ${col.rules.map((r) => `${r.column} ${r.relation} ${r.condition}`).join(' AND ')}`);
      continue;
    }
    const data = await gql(
      `mutation($input: CollectionInput!) {
        collectionCreate(input: $input) { collection { id } userErrors { message } }
      }`,
      {
        input: {
          title: col.title,
          handle: col.handle,
          templateSuffix: col.templateSuffix,
          sortOrder: col.sortOrder || 'BEST_SELLING',
          ruleSet: { appliedDisjunctively: false, rules: col.rules }
        }
      }
    );
    const r = data.collectionCreate;
    report(col.handle, r.userErrors);
    if (r.collection && publicationId) {
      await gql(
        `mutation($id: ID!, $p: ID!) { publishablePublish(id: $id, input: { publicationId: $p }) { userErrors { message } } }`,
        { id: r.collection.id, p: publicationId }
      );
    }
  }
}

const metaobjectIds = {
  drop: await createMetaobject(DROP_METAOBJECT),
  collector: await createMetaobject(COLLECTOR_METAOBJECT)
};
const productMf = await createMetafields('PRODUCT', PRODUCT_METAFIELDS, metaobjectIds);
await createMetafields('COLLECTION', COLLECTION_METAFIELDS, metaobjectIds);
await createMetafields('CUSTOMER', CUSTOMER_METAFIELDS, metaobjectIds);
await createCollections(productMf);
console.log('\nDone. Next: enable filters in Search & Discovery (see docs/setup.md).');
