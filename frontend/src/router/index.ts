import ExplorerView from '@/views/ExplorerView.vue'
import { createRouter, createWebHashHistory } from 'vue-router'

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
