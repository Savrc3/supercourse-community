import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'icons.svg'],
      manifest: {
        name: '课序 · 个人课表与学习事务管理',
        short_name: '课序',
        description: '本地优先的个人课表与学习事务管理工具',
        lang: 'zh-CN',
        display: 'standalone',
        start_url: '/',
        background_color: '#111522',
        theme_color: '#3859D6',
        icons: [
          { src: '/pwa/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/pwa/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/media/'),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'media-cache',
              expiration: { maxEntries: 200, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
          {
            urlPattern: ({ url }) => url.pathname === '/index.html',
            handler: 'NetworkFirst',
            options: { cacheName: 'doc-cache' },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
})
