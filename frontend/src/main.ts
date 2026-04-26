import './assets/main.css'

import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

import piniaPluginPersistedState from 'pinia-plugin-persistedstate'

import ContextMenu from '@imengyu/vue3-context-menu'
import '@imengyu/vue3-context-menu/lib/vue3-context-menu.css'

const app = createApp(App)
app.config.errorHandler = err => {
  /* handle error */
  console.log(err)
}

const pinia = createPinia()
pinia.use(piniaPluginPersistedState)
app.use(pinia)
app.use(router)
app.use(ContextMenu)
app.mount('#app')
