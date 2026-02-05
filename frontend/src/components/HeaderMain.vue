<template>
  <nav class="headermain buttons">
    <UploadButton :path="props.path" />
    <SvgButton
      name="create-folder"
      tooltip="New folder"
      @click="() => { store.fileExplorer!.newFolder() }"
    />
    <div class="smallgap"></div>
    <SvgButton name="eye" @click="store.prefs.gallery = !store.prefs.gallery" tooltip="Details/Gallery" />
    <div class="search-group">
      <SvgButton name="find" tabindex="-1" @click="focusSearch" tooltip="Search" />
      <input
        ref="search"
        type="search"
        :value="query"
        @input="updateSearch"
        @keydown.escape="clearSearch"
      />
      <span v-if="!query" class="search-hint" @click="focusSearch">/</span>
    </div>
    <div class="spacer smallgap"></div>
    <DiskSpace v-if="store.space.disk" />
    <SvgButton name="cog" @click="settingsMenu" />
  </nav>
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import { useSsoAuthStore } from '@/stores/ssoAuth'
import { ref } from 'vue'
import ContextMenu from '@imengyu/vue3-context-menu'
import { showAuthIframe } from 'paskia'
import { resumeWatching } from '@/repositories/WS'
import router from '@/router';
import DiskSpace from './DiskSpace.vue'

const store = useMainStore()
const ssoStore = useSsoAuthStore()
const search = ref<HTMLInputElement | null>()

const props = defineProps<{
  path: Array<string>
  query: string
}>()

const clearSearch = (ev: Event) => {
  const input = search.value
  if (input) {
    input.value = ''
    updateSearch(ev)
  }
  const breadcrumb = document.querySelector('.breadcrumb') as HTMLElement
  breadcrumb.focus()
}

const focusSearch = () => {
  search.value?.focus()
}

// Track pending route update
let pendingRouteUpdate: number | null = null

const updateSearch = (ev: Event) => {
  const q = (ev.target as HTMLInputElement).value
  const loc = props.path.join('/')

  // Start search immediately via store (worker handles it async)
  store.search(q, loc)

  // Cancel any pending route update
  if (pendingRouteUpdate !== null) {
    cancelAnimationFrame(pendingRouteUpdate)
  }

  // Schedule route update - will be cancelled if user types again
  pendingRouteUpdate = requestAnimationFrame(() => {
    pendingRouteUpdate = null
    let p = loc
    p = p ? `/${p}` : ''
    const url = q ? `${p}//${q}` : (p || '/')
    const u = url.replaceAll('?', '%3F').replaceAll('#', '%23')
    // Use replace to avoid building up history for each keystroke
    router.replace(u)
  })
}

const toggleSearchInput = () => {
  search.value?.focus()
}
const settingsMenu = (e: Event) => {
  // show the context menu
  const items = []

  // For external auth, show user name as link to /auth/
  if (ssoStore.isExternalAuth && store.user.isLoggedIn) {
    items.push({
      label: '👤 ' + (store.user.username || 'User Account'),
      onClick: () => { window.location.href = '/auth/' }
    })
  }

  // Only show password change for non-SSO users
  if (!ssoStore.isExternalAuth && store.user.isLoggedIn) {
    items.push({ label: '🔑 Change Password', onClick: () => { store.dialog = 'settings' }})
  }

  if (store.user.privileged) {
    items.push({ label: '⚙️ Admin Settings', onClick: () => { store.dialog = 'usermgmt' }})
  }

  if (store.user.isLoggedIn) {
    items.push({ label: '🚪 Logout', onClick: () => store.logout() })
  } else if (store.server.public) {
    // Show login option only in public mode (non-public modes trigger auth automatically)
    items.push({ label: '🔐 Login', onClick: async () => {
      try {
        await showAuthIframe('/auth/restricted/#theme=light')
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
  clearSearch,
})
</script>

<style scoped>
.buttons {
  flex: 1000 0 auto;
  padding: 0;
  display: flex;
  align-items: center;
  z-index: 10;
  min-height: 3em;
}
.search-group {
  position: relative;
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 1.5em;
  padding: 0 0.3em;
  transition: background 0.2s ease;
  flex: 1 1 auto;
  min-width: 2.5em;
  max-width: 20em;
}
.search-group:hover,
.search-group:focus-within {
  background: rgba(255, 255, 255, 0.2);
}
.search-group:focus-within {
  box-shadow: 0 0 0 2px var(--accent-color, #f80);
}
.search-group:hover :deep(button.action-button),
.search-group:focus-within :deep(button.action-button) {
  transform: scale(1.1);
}
.search-group:hover :deep(button.action-button svg),
.search-group:focus-within :deep(button.action-button svg) {
  fill: #fff;
}
.search-group:focus-within .search-hint {
  opacity: 0;
  pointer-events: none;
}
.search-group :deep(.action-button) {
  width: 2.2em;
  height: 2.2em;
  min-width: 1.5em;
  min-height: 1.5em;
  flex-shrink: 0;
}
.search-group input[type='search'] {
  background: transparent;
  color: var(--header-color);
  border: none;
  outline: none;
  padding: 0.2em 0.5em 0.2em 0;
  font-size: inherit;
  flex: 1 1 3em;
  min-width: 0;
  width: 100%;
}
.search-hint {
  position: absolute;
  right: 0.5em;
  font-family: system-ui, sans-serif;
  font-size: 1em;
  font-weight: 700;
  color: #333;
  background: #ccc;
  border: 1px solid #999;
  border-radius: 0.3em;
  padding: 0 0.45em;
  line-height: 1.4;
  cursor: pointer;
  transition: opacity 0.15s ease;
  display: none;
}
@media (hover: hover) and (pointer: fine) {
  .search-hint {
    display: block;
  }
}
</style>
