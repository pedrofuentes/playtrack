import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: 'generateSW',
      registerType: 'autoUpdate',
      injectRegister: false,
      includeAssets: [
        'brand/playtrack-mark.svg',
        'brand/playtrack-lockup.svg',
        'favicon-16.png',
        'favicon-32.png',
        'favicon-48.png',
        'apple-touch-icon.png',
      ],
      manifest: {
        name: 'PlayTrack',
        short_name: 'PlayTrack',
        description: 'A local virtual camera for panoramic sports footage.',
        theme_color: '#080b0f',
        background_color: '#080b0f',
        display: 'standalone',
        start_url: './',
        scope: './',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'pwa-maskable-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'pwa-maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{html,js,css,svg,png,webmanifest}'],
        globIgnores: [
          '**/*.mp4',
          '**/*.mov',
          '**/*.mkv',
          '**/*.webm',
          'api/**',
          'ws/**',
          'exports/**',
          'data/**',
        ],
        navigateFallbackDenylist: [
          /^\/api(?:\/|$)/,
          /^\/ws(?:\/|$)/,
          /^\/exports(?:\/|$)/,
          /^\/data(?:\/|$)/,
          /\.(?:mp4|mov|mkv|webm)$/i,
        ],
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
