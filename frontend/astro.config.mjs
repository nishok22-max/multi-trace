import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  output: 'static',
  integrations: [react()],
  // Never inline CSS: the CSP uses style-src 'self' plus hashes from dist/csp-hashes.json.
  build: { inlineStylesheets: 'never' },
  vite: {
    plugins: [tailwindcss()],
    server: {
      proxy: { '/api': 'http://127.0.0.1:8000' },
    },
  },
});
