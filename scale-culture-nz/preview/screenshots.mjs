#!/usr/bin/env node
// Screenshots the built preview at phone and desktop widths into ../docs/screenshots.
import { chromium } from 'playwright-core';
import { mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, '..', 'docs', 'screenshots');
await mkdir(OUT, { recursive: true });
const url = (p) => pathToFileURL(join(here, 'dist', p)).href;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

async function shot(ctx, page, file, { full = false, before } = {}) {
  const p = await ctx.newPage();
  await p.goto(url(page), { waitUntil: 'networkidle' }).catch(() => {});
  await p.evaluate(() => document.querySelectorAll('img[loading="lazy"]').forEach((i) => (i.loading = 'eager')));
  await p.waitForTimeout(500);
  if (before) await before(p);
  await p.screenshot({ path: join(OUT, file), fullPage: full, type: 'jpeg', quality: 80 });
  await p.close();
  console.log(`  ✓ ${file}`);
}
const openDrawer = async (p) => {
  await p.evaluate(() => {
    const d = document.querySelector('[data-cart-drawer]');
    d.hidden = false;
    d.classList.add('is-open');
  });
  await p.waitForTimeout(300);
};

await shot(desktop, 'index.html', 'home-desktop.jpg', { full: true });
await shot(mobile, 'index.html', 'home-mobile.jpg', { full: true });
await shot(desktop, 'product.html', 'product-desktop.jpg');
await shot(desktop, 'product-preorder.html', 'product-preorder-desktop.jpg', { full: false });
await shot(mobile, 'product.html', 'product-mobile-sticky-atc.jpg', { before: (p) => p.evaluate(() => { window.scrollTo(0, 1500); }).then(() => p.waitForTimeout(400)) });
await shot(mobile, 'product-sold-out.html', 'product-sold-out-mobile.jpg', { full: true });
await shot(desktop, 'collection.html', 'collection-desktop.jpg');
await shot(mobile, 'collection.html', 'collection-filters-mobile.jpg', { before: (p) => p.click('[data-facets-open]').then(() => p.waitForTimeout(400)) });
await shot(desktop, 'product.html', 'cart-drawer-desktop.jpg', { before: openDrawer });
await shot(mobile, 'product.html', 'cart-drawer-mobile.jpg', { before: openDrawer });
await shot(desktop, 'cart.html', 'cart-desktop.jpg');
await shot(desktop, 'journal.html', 'journal-desktop.jpg', { full: true });
await shot(desktop, 'article.html', 'article-desktop.jpg', { full: true });
await shot(desktop, 'drop.html', 'drop-desktop.jpg');
await shot(desktop, 'garage.html', 'garage-desktop.jpg', { full: true });
await shot(desktop, 'dashboard.html', 'dashboard-desktop.jpg', { full: true });
await shot(mobile, 'dashboard.html', 'dashboard-mobile.jpg', { full: true });
await browser.close();
