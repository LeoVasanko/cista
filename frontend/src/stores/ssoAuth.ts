import { defineStore } from 'pinia'
import { computed } from 'vue'
import { useMainStore } from './main'
import { clearTree } from '@/repositories/WS'

export const useSsoAuthStore = defineStore('ssoAuth', () => {
  const isExternalAuth = computed(() => {
    const mainStore = useMainStore()
    return mainStore.server?.paskia === true
  })

  function clearDataOnUnauth() {
    const mainStore = useMainStore()
    mainStore.clearSensitiveData()
    clearTree()
  }

  return { isExternalAuth, clearDataOnUnauth }
})
