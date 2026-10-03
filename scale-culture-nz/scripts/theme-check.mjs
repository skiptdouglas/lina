#!/usr/bin/env node
// Runs Shopify's theme-check on theme/ and fails on errors (warnings are printed).
//   npm install --no-save --prefix .ci @shopify/theme-check-node && node scripts/theme-check.mjs
import { createRequire } from 'node:module';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(join(root, '.ci', 'package.json'));
const { themeCheckRun } = await import(require.resolve('@shopify/theme-check-node'));
const theme = join(root, 'theme');
const { offenses } = await themeCheckRun(theme, undefined, () => {});
const label = ['ERROR', 'WARN', 'INFO'];
for (const o of offenses) console.log(`${label[o.severity] ?? o.severity} ${o.uri.replace(`file://${theme}`, 'theme')}:${o.start.line + 1} [${o.check}] ${o.message}`);
const errors = offenses.filter((o) => o.severity === 0).length;
console.log(`${offenses.length} offenses, ${errors} errors`);
process.exit(errors ? 1 : 0);
