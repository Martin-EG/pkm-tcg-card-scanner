/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Paths served by the shop server (server/api/routes/); proxied during `npm run dev`.
const API = ['/settings', '/identify', '/corrections', '/sessions', '/images', '/scans', '/certificado']

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Compra de cartas Pokémon',
        short_name: 'Compra TCG',
        lang: 'es-MX',
        start_url: '/',
        display: 'standalone',
        background_color: '#f6f4ef',
        theme_color: '#c8102e',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        // Only the app shell is cached; API answers always come from the server.
        navigateFallbackDenylist: API.map((p) => new RegExp(`^${p}`)),
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    proxy: Object.fromEntries(API.map((p) => [p, 'http://127.0.0.1:8000'])),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
