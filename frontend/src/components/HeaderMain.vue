<template>
  <nav class="headermain buttons">
    <template v-if="store.error">
      <div class="error-message" @click="store.error = ''">{{ store.error }}</div>
      <div class="smallgap"></div>
    </template>
    <UploadButton :path="props.path" />
    <SvgButton
      name="create-folder"
      data-tooltip="New folder"
      @click="() => {  console.log('New', store.fileExplorer); store.fileExplorer!.newFolder(); console.log('Done')}"
    />
    <slot></slot>
    <div class="spacer smallgap"></div>
    <template v-if="showSearchInput">
      <input
        ref="search"
        type="search"
        :value="query"
        @input="updateSearch"
        placeholder="Find files"
        class="margin-input"
      />
    </template>
    <SvgButton ref="searchButton" name="find" @click.prevent="toggleSearchInput" />
    <SvgButton name="eye" @click="store.prefs.gallery = !store.prefs.gallery" />
    <SvgButton name="cog" @click="settingsMenu" />
  </nav>
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import { useSsoAuthStore } from '@/stores/ssoAuth'
import { ref, nextTick, watchEffect, computed } from 'vue'
import ContextMenu from '@imengyu/vue3-context-menu'
import { showAuthIframe } from 'paskia'
import { resumeWatching } from '@/repositories/WS'
import router from '@/router';

const store = useMainStore()
const ssoStore = useSsoAuthStore()
const showSearchInput = ref<boolean>(false)
const search = ref<HTMLInputElement | null>()
const searchButton = ref<HTMLButtonElement | null>()

// Display name for SSO users
const displayUserName = computed(() => {
  if (ssoStore.isExternalAuth && ssoStore.userName) {
    return ssoStore.userName
  }
  return store.user.username
})

  const props = defineProps<{
  path: Array<string>
  query: string
}>()

const closeSearch = (ev: Event) => {
  if (!showSearchInput.value) return  // Already closing
  showSearchInput.value = false
  const breadcrumb = document.querySelector('.breadcrumb') as HTMLElement
  breadcrumb.focus()
  updateSearch(ev)
}
const updateSearch = (ev: Event) => {
  const q = (ev.target as HTMLInputElement).value
  let p = props.path.join('/')
  p = p ? `/${p}` : ''
  const url = q ? `${p}//${q}` : (p || '/')
  const u = url.replaceAll('?', '%3F').replaceAll('#', '%23')
  if (!props.query && q) router.push(u)
  else router.replace(u)
}
const toggleSearchInput = (ev: Event) => {
  showSearchInput.value = !showSearchInput.value
  if (!showSearchInput.value) return closeSearch(ev)
  nextTick(() => {
    const input = search.value
    if (input) input.focus()
  })
}
watchEffect(() => {
  if (props.query) showSearchInput.value = true
})
const settingsMenu = (e: Event) => {
  // show the context menu
  const items = []

  // For external auth, show user name as link to /auth/
  if (ssoStore.isExternalAuth && store.user.isLoggedIn) {
    items.push({
      label: displayUserName.value || 'User Account',
      onClick: () => { window.location.href = '/auth/' }
    })
    items.push({ divided: true })
  }

  // Only show password change for non-SSO users
  if (!ssoStore.isExternalAuth) {
    items.push({ label: 'Change Password', onClick: () => { store.dialog = 'settings' }})
  }

  if (store.user.privileged) {
    items.push({ label: 'Admin Settings', onClick: () => { store.dialog = 'usermgmt' }})
  }

  if (store.user.isLoggedIn) {
    if (ssoStore.isExternalAuth) {
      // For SSO, link to auth logout
      items.push({ label: 'Logout', onClick: () => { window.location.href = '/auth/' }})
    } else {
      items.push({ label: `Logout ${store.user.username ?? ''}`, onClick: () => store.logout() })
    }
  } else if (!ssoStore.isExternalAuth) {
    // Show login in paskia iframe overlay
    items.push({ label: 'Login', onClick: async () => {
      try {
        await showAuthIframe('/auth/api/restricted')
        resumeWatching()
      } catch (e) {
        console.log('Login cancelled')
      }
    }})
  }
  ContextMenu.showContextMenu({
    // @ts-ignore
    x: e.target.getBoundingClientRect().right, y: e.target.getBoundingClientRect().bottom,
    items,
  })
}
defineExpose({
  toggleSearchInput,
  closeSearch,
})
</script>

<style scoped>
.buttons {
  flex: 1000 0 auto;
  padding: 0;
  display: flex;
  align-items: center;
  z-index: 10;
}
input[type='search'] {
  background: var(--input-background);
  color: var(--input-color);
  border: 0;
  border-radius: 0.1em;
  outline: none;
  max-width: 15ch;
}
</style>
