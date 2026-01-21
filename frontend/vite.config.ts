import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// @ts-ignore
import svgLoader from 'vite-svg-loader'
import Components from 'unplugin-vue-components/vite'

const dev_backend = {
  target: process.env.CISTA_BACKEND_URL || "http://localhost:8989",
  changeOrigin: false,  // Use frontend "host" to match "origin" from browser
  ws: true,
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    svgLoader(),          // import svg files
    Components(),         // auto import components
  ],
  css: {
    preprocessorOptions: {
      less: {
        modifyVars: {},
        javascriptEnabled: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      "/api": dev_backend,
      "/files": dev_backend,
      "/login": dev_backend,
      "/logout": dev_backend,
      "/password-change": dev_backend,
      "/zip": dev_backend,
      "/preview": dev_backend,
    }
  },
  build: {
    outDir: "../cista/frontend-build",
    emptyOutDir: true,
  }
})
