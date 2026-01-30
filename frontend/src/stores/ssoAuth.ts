import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useMainStore } from './main'
import { SessionValidator, apiFetch, AuthCancelledError } from 'paskia'

// Session validator instance (only used in paskia mode)
let sessionValidator: SessionValidator | null = null

export const useSsoAuthStore = defineStore('ssoAuth', () => {
  // State
  const userName = ref('')
  const userUuid = ref('')

  // Getters
  const isExternalAuth = computed(() => {
    const mainStore = useMainStore()
    return mainStore.server?.authentication === 'paskia'
  })

  // Actions
  function clearDataOnUnauth() {
    const mainStore = useMainStore()
    // Clear localStorage
    localStorage.removeItem('cista-files')
    // Clear visible files by resetting document
    mainStore.document = []
    mainStore.selected.clear()
    mainStore.user.isLoggedIn = false
    userName.value = ''
    userUuid.value = ''
  }

  function handleSessionLost(error: Error) {
    console.warn('Session lost:', error)
    clearDataOnUnauth()
    // Trigger re-authentication by reloading - paskia will handle the auth flow
    location.reload()
  }

  async function validateSession(): Promise<boolean> {
    // Only do session validation in paskia mode
    if (!isExternalAuth.value) return true

    try {
      const res = await apiFetch('/auth/api/validate', {
        method: 'POST',
        headers: { 'accept': 'application/json' }
      })
      if (res.ok) {
        // Extract user display name from Remote-Name header
        userName.value = res.headers.get('Remote-Name') || ''
        try {
          const data = await res.json()
          if (data.uuid) userUuid.value = data.uuid
        } catch {
          // Response may not have JSON body
        }
        return true
      }
      return false
    } catch (e) {
      if (e instanceof AuthCancelledError) {
        console.log('User cancelled authentication')
        return false
      }
      console.error('SSO validation error:', e)
      return false
    }
  }

  function startValidationPolling() {
    if (!isExternalAuth.value) return

    // Stop any existing validator
    stopValidationPolling()

    // Initial validation to get user info
    validateSession()

    // Use paskia's SessionValidator for ongoing session monitoring
    sessionValidator = new SessionValidator(
      () => userUuid.value || undefined,  // getter for current user ID
      handleSessionLost  // callback when session is lost
    )
    sessionValidator.start()
  }

  function stopValidationPolling() {
    if (sessionValidator) {
      sessionValidator.stop()
      sessionValidator = null
    }
  }

  return {
    // State
    userName,
    userUuid,
    // Getters
    isExternalAuth,
    // Actions
    validateSession,
    clearDataOnUnauth,
    startValidationPolling,
    stopValidationPolling,
  }
})
