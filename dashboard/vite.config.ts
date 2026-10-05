import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const api = process.env.AURORA_API ?? 'http://127.0.0.1:8765'

export default defineConfig({
  // the static demo is served from a sub-path (GitHub Pages), so use relative asset URLs
  base: process.env.VITE_STATIC === '1' ? './' : '/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': api,
      '/ws': { target: api.replace('http', 'ws'), ws: true },
    },
  },
})
