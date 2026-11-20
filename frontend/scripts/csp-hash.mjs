// CSP spike (C-01): hash every inline <script> and <style> in dist/**/*.html
// and write dist/csp-hashes.json. Run after `astro build`.
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist');

function* htmlFiles(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* htmlFiles(p);
    else if (name.endsWith('.html')) yield p;
  }
}

const sha = (text) => `'sha256-${createHash('sha256').update(text, 'utf8').digest('base64')}'`;
const scripts = new Set();
const styles = new Set();

for (const file of htmlFiles(dist)) {
  const html = readFileSync(file, 'utf8');
  for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (!/\bsrc\s*=/.test(m[1]) && m[2].length > 0) scripts.add(sha(m[2]));
  }
  for (const m of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) {
    if (m[1].length > 0) styles.add(sha(m[1]));
  }
}

const out = { scripts: [...scripts].sort(), styles: [...styles].sort() };
writeFileSync(join(dist, 'csp-hashes.json'), JSON.stringify(out, null, 2) + '\n');
console.log(`csp-hashes.json: ${out.scripts.length} script, ${out.styles.length} style hashes`);
