import { URL, fileURLToPath } from 'node:url'
import fastapiVue from './vite-plugin-fastapi.js'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

import Components from 'unplugin-vue-components/vite'
// @ts-ignore
import svgLoader from 'vite-svg-loader'

// https://vitejs.dev/config/
// Note: fastapiVue() handles proxy and build output (uses FASTAPI_VUE_BACKEND_URL env)
export default defineConfig({
  plugins: [
    fastapiVue({ paths: ['/api', '/auth', '/files', '/zip', '/preview'] }),
    vue(),
    svgLoader(), // import svg files
    Components() // auto import components
  ],
  css: {
    preprocessorOptions: {
      less: {
        modifyVars: {},
        javascriptEnabled: true
      }
    }
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Bundle all SVG icons into a single chunk
          icons: ['/src/assets/svg/index.ts']
        }
      }
    }
  }
})
