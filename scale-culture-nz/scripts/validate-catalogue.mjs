#!/usr/bin/env node
// Checks a Shopify product CSV against the Scale Culture NZ product data standard
// (SOP §12 data, §13 naming, §15 stock states, §17 pre-orders, §22 search, §29 inventory,
// §30 images, §32 SEO). Run before every import.
//
//   node validate-catalogue.mjs ../data/product-import-template.csv
//   node validate-catalogue.mjs products.csv --fix-tags > products.fixed.csv
//
// --fix-tags adds missing search tags (make, model, generation, scale) so searching
// "R34" or "Porsche" finds every brand's version (SOP §22).

import { readFileSync } from 'node:fs';
import { SCALES, VEHICLE_MAKES, VEHICLE_MODELS, AVAILABILITY, PRODUCT_TYPES, MOTORSPORT } from './catalogue-schema.mjs';

const file = process.argv[2];
const FIX_TAGS = process.argv.includes('--fix-tags');
if (!file) {
  console.error('Usage: node validate-catalogue.mjs <products.csv> [--fix-tags]');
  process.exit(2);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field); rows.push(row); row = []; field = '';
    } else field += ch;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((c) => c !== ''));
}

const toCsv = (rows) =>
  rows.map((r) => r.map((c) => (/[",\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(',')).join('\n') + '\n';

const [header, ...body] = parseCsv(readFileSync(file, 'utf8'));
const col = (name) => {
  const i = header.findIndex((h) => h === name || h.endsWith(`(product.metafields.scale.${name})`));
  return i;
};
const get = (row, name) => {
  const i = col(name);
  return i >= 0 ? (row[i] || '').trim() : '';
};

// Group rows by handle: first row holds product data, following rows add images.
const products = new Map();
for (const row of body) {
  const handle = get(row, 'Handle');
  if (!products.has(handle)) products.set(handle, { row, images: [], alts: [] });
  const p = products.get(handle);
  if (get(row, 'Image Src')) {
    p.images.push(get(row, 'Image Src'));
    p.alts.push(get(row, 'Image Alt Text'));
  }
}

const issues = [];
const add = (level, handle, msg) => issues.push({ level, handle, msg });
const seoTitles = new Map();
const seoDescs = new Map();
const VAGUE = /^(purple|red|blue|white|black|silver|green|yellow)\s+\w+$/i;

for (const [handle, { row, images, alts }] of products) {
  const title = get(row, 'Title');
  const vendor = get(row, 'Vendor');
  const scale = get(row, 'scale');
  const make = get(row, 'vehicle_make');
  const model = get(row, 'vehicle_model');
  const gen = get(row, 'vehicle_generation');
  const availability = get(row, 'availability') || 'auto';
  const type = get(row, 'Type');
  const qty = parseInt(get(row, 'Variant Inventory Qty') || '0', 10);
  const policy = get(row, 'Variant Inventory Policy');
  const status = get(row, 'Status');

  // Required (SOP §12)
  for (const [label, value] of [
    ['SKU', get(row, 'Variant SKU')], ['Title', title], ['Vendor (brand)', vendor], ['Price', get(row, 'Variant Price')],
    ['Type', type], ['Scale', scale], ['Vehicle manufacturer', make], ['Vehicle model', model]
  ]) {
    if (!value && !(type === 'Accessory' && /Scale|Vehicle/.test(label))) add('error', handle, `missing ${label}`);
  }
  if (get(row, 'Variant Inventory Tracker') !== 'shopify') add('error', handle, 'inventory must be tracked by Shopify');
  if (type && !PRODUCT_TYPES.includes(type)) add('error', handle, `Type "${type}" not one of ${PRODUCT_TYPES.join(', ')}`);
  if (scale && !SCALES.includes(scale)) add('error', handle, `Scale "${scale}" not one of ${SCALES.join(', ')}`);
  if (make && !VEHICLE_MAKES.includes(make)) add('error', handle, `Vehicle manufacturer "${make}" not in the allowed list`);
  if (model && VEHICLE_MODELS[make] && !(model in VEHICLE_MODELS[make])) add('warn', handle, `vehicle model "${model}" is new for ${make} — check spelling matches existing products`);
  if (gen && VEHICLE_MODELS[make]?.[model]?.length && !VEHICLE_MODELS[make][model].includes(gen)) add('warn', handle, `generation "${gen}" is new for ${make} ${model}`);
  if (!AVAILABILITY.includes(availability)) add('error', handle, `availability "${availability}" not one of ${AVAILABILITY.join(', ')}`);
  const motorsport = get(row, 'motorsport_category');
  if (motorsport && !MOTORSPORT.includes(motorsport)) add('error', handle, `motorsport category "${motorsport}" not allowed`);

  // Naming: Brand – Vehicle – Variant – Scale (SOP §13)
  if (title) {
    const parts = title.split(/\s+[–-]\s+/);
    if (parts.length < 3) add('error', handle, `title should be "Brand – Vehicle – Variant – Scale", got "${title}"`);
    if (vendor && parts[0] !== vendor) add('error', handle, `title should start with the brand "${vendor}"`);
    if (scale && scale !== 'Other' && parts[parts.length - 1] !== scale) add('error', handle, `title should end with the scale "${scale}"`);
    if (VAGUE.test(title)) add('error', handle, 'title is vague — name the brand, vehicle and variant');
  }

  // Stock / inventory workflow (SOP §15, §29)
  if (availability === 'preorder') {
    if (policy !== 'continue') add('error', handle, 'pre-orders need Variant Inventory Policy = continue (set Qty to the allocation)');
    if (!get(row, 'preorder_jp_release') || !get(row, 'preorder_nz_arrival')) add('error', handle, 'pre-order missing expected Japanese release / NZ arrival');
  } else if (policy === 'continue') {
    add('error', handle, 'overselling (policy=continue) is only allowed on pre-orders');
  }
  if ((availability === 'coming_soon' || availability === 'incoming') && qty > 0) {
    add('error', handle, `stock is ${availability} but has quantity ${qty} — only add quantity once physically verified`);
  }
  if (availability === 'auto' && qty === 0 && status === 'active') add('info', handle, 'active with 0 stock — will show SOLD OUT');

  // Images (SOP §30)
  if (images.length === 0) add(status === 'active' ? 'error' : 'warn', handle, 'no images');
  else if (images.length < 3) add('warn', handle, `${images.length} image(s) — aim for 3: front 3/4, rear, packaging`);
  if (alts.some((a) => !a)) add('error', handle, 'every image needs ALT text');

  // SEO (SOP §32)
  const seoTitle = get(row, 'SEO Title');
  const seoDesc = get(row, 'SEO Description');
  if (status === 'active') {
    if (!seoTitle) add('error', handle, 'missing SEO title');
    if (!seoDesc) add('error', handle, 'missing SEO description');
  }
  if (seoTitle) {
    if (seoTitles.has(seoTitle)) add('error', handle, `SEO title duplicates ${seoTitles.get(seoTitle)}`);
    seoTitles.set(seoTitle, handle);
    if (seoTitle.length > 70) add('warn', handle, `SEO title is ${seoTitle.length} chars (keep ≤ 70)`);
  }
  if (seoDesc) {
    if (seoDescs.has(seoDesc)) add('error', handle, `SEO description duplicates ${seoDescs.get(seoDesc)}`);
    seoDescs.set(seoDesc, handle);
    if (seoDesc.length > 160) add('warn', handle, `SEO description is ${seoDesc.length} chars (keep ≤ 160)`);
  }

  // Search tags (SOP §22)
  const tags = get(row, 'Tags').split(',').map((t) => t.trim()).filter(Boolean);
  const wanted = [make, model, gen, scale].filter(Boolean);
  const missing = wanted.filter((w) => !tags.some((t) => t.toLowerCase() === w.toLowerCase()));
  if (missing.length) {
    if (FIX_TAGS) row[col('Tags')] = [...tags, ...missing].join(', ');
    else add('warn', handle, `search tags missing: ${missing.join(', ')} (run with --fix-tags)`);
  }
}

if (FIX_TAGS) {
  process.stdout.write(toCsv([header, ...body]));
}

const out = FIX_TAGS ? console.error : console.log;
const icon = { error: '✗', warn: '!', info: 'i' };
for (const i of issues) out(`${icon[i.level]} ${i.handle}: ${i.msg}`);
const errors = issues.filter((i) => i.level === 'error').length;
const warns = issues.filter((i) => i.level === 'warn').length;
out(`\n${products.size} products · ${errors} errors · ${warns} warnings`);
process.exit(errors ? 1 : 0);
