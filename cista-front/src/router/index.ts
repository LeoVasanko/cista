import { createRouter, createWebHashHistory } from 'vue-router'
import ExplorerView from '@/views/ExplorerView.vue'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/:pathMatch(.*)*',
      name: 'explorer',
      component: ExplorerView
    }
  ]
})

export default router
