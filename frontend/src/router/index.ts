import { useMainStore } from '@/stores/main'
import ExplorerView from '@/views/ExplorerView.vue'
import { createRouter, createWebHashHistory } from 'vue-router'

function getPathDepth(path: string): number {
  const pathPart = decodeURIComponent(path).split('//')[0] ?? ''
  return pathPart.split('/').filter(Boolean).length
}

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

router.beforeEach((to, from) => {
  const store = useMainStore()
  const toDepth = getPathDepth(to.path)
  const fromDepth = getPathDepth(from.path)
  if (toDepth > fromDepth) {
    store.transitionDirection = 'forward'
  } else if (toDepth < fromDepth) {
    store.transitionDirection = 'backward'
  } else {
    store.transitionDirection = 'none'
  }
})

export default router
