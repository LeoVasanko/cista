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
      <SvgButton name="find" @click="focusSearch" tooltip="Search" />
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
    <div v-if="store.space.disk" class="disk-space"
      @mouseenter="diskTooltip?.startHover"
      @mousemove="diskTooltip?.updatePosition"
      @mouseleave="diskTooltip?.endHover"
    >
      <svg viewBox="0 0 32 32" class="pie-mini">
        <!-- Base: 'other' usage (light purple - appears on left, before 12 o'clock) -->
        <circle r="16" cx="16" cy="16" fill="#c8e" />
        <!-- Middle ring: free space (dynamic color - appears at bottom) -->
        <circle r="8" cx="16" cy="16" fill="transparent" :stroke="freeColor" stroke-width="16" :stroke-dasharray="pieFree" :stroke-dashoffset="pieFreeOffset" transform="rotate(-90 16 16)" />
        <!-- Top ring: storage (deep purple - appears on right after 12 o'clock) -->
        <circle r="8" cx="16" cy="16" fill="transparent" stroke="#82d" stroke-width="16" :stroke-dasharray="pieStorage" transform="rotate(-90 16 16)" />
        <!-- Subtle inner circle for depth -->
        <circle r="2" cx="16" cy="16" fill="rgba(255,255,255,0.2)" />
      </svg>
      <CursorTooltip ref="diskTooltip" text="Disk space">
        <div class="disk-tooltip">
          <svg viewBox="0 0 160 80" width="160" height="80" class="pie-tooltip">
            <!-- Pie chart centered at 40,40 -->
            <circle r="32" cx="40" cy="40" fill="#c8e" />
            <circle r="16" cx="40" cy="40" fill="transparent" :stroke="freeColor" stroke-width="32" :stroke-dasharray="pieFreeLg" :stroke-dashoffset="pieFreeOffsetLg" transform="rotate(-90 40 40)" />
            <circle r="16" cx="40" cy="40" fill="transparent" stroke="#82d" stroke-width="32" :stroke-dasharray="pieStorageLg" transform="rotate(-90 40 40)" />
            <circle r="4" cx="40" cy="40" fill="rgba(255,255,255,0.25)" />
            <!-- Labels on the right -->
            <rect x="78" y="10" width="10" height="10" fill="#82d" rx="2"/>
            <text x="92" y="19" class="pie-label">{{ formatSize(store.space.storage) }} stored</text>
            <rect x="78" y="30" width="10" height="10" fill="#c8e" rx="2"/>
            <text x="92" y="39" class="pie-label">{{ formatSize(store.space.usage - store.space.storage) }} other</text>
            <rect x="78" y="50" width="10" height="10" :fill="freeColor" rx="2"/>
            <text x="92" y="59" class="pie-label">{{ formatSize(store.space.free) }} free</text>
          </svg>
        </div>
      </CursorTooltip>
    </div>
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
import { formatSize } from '@/utils'
import CursorTooltip from './CursorTooltip.vue'

const store = useMainStore()
const ssoStore = useSsoAuthStore()
const search = ref<HTMLInputElement | null>()
const diskTooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)

const CIRC = 50.27  // 2π×8

// Storage segment (starts at top, -90°)
const pieStorage = computed(() => {
  const s = store.space
  if (!s.disk) return `0 ${CIRC}`
  const pct = s.storage / s.disk
  return `${pct * CIRC} ${CIRC}`
})

// Free segment (starts after storage, goes clockwise to bottom area)
const pieFree = computed(() => {
  const s = store.space
  if (!s.disk) return `0 ${CIRC}`
  const pct = s.free / s.disk
  return `${pct * CIRC} ${CIRC}`
})

const pieFreeOffset = computed(() => {
  const s = store.space
  if (!s.disk) return 0
  // Start after storage segment
  const storagePct = s.storage / s.disk
  return -storagePct * CIRC
})

// Free space color: green when plenty, yellow when moderate, red when low
const freeColor = computed(() => {
  const s = store.space
  if (!s.disk) return '#6c6'
  const freePct = s.free / s.disk
  if (freePct > 0.25) return '#5b5'  // Green: > 25% free
  if (freePct > 0.10) return '#db3'  // Yellow: 10-25% free
  return '#d44'  // Red: < 10% free
})

// Large pie for tooltip (circumference = 2π×16 ≈ 100.53)
const CIRC_LG = 100.53
const pieStorageLg = computed(() => {
  const s = store.space
  if (!s.disk) return `0 ${CIRC_LG}`
  return `${(s.storage / s.disk) * CIRC_LG} ${CIRC_LG}`
})
const pieFreeLg = computed(() => {
  const s = store.space
  if (!s.disk) return `0 ${CIRC_LG}`
  return `${(s.free / s.disk) * CIRC_LG} ${CIRC_LG}`
})
const pieFreeOffsetLg = computed(() => {
  const s = store.space
  if (!s.disk) return 0
  return -(s.storage / s.disk) * CIRC_LG
})

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
        await showAuthIframe('/auth/restricted#theme=light')
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
  min-width: 5.5em;
  max-width: 20em;
}
.search-group:focus-within {
  background: rgba(255, 255, 255, 0.2);
}
.search-group:focus-within .search-hint {
  opacity: 0;
  pointer-events: none;
}
.search-group :deep(.action-button) {
  width: 2.2em;
  height: 2.2em;
  flex-shrink: 0;
}
.search-group input[type='search'] {
  background: transparent;
  color: var(--header-color);
  border: none;
  outline: none;
  padding: 0.2em 0.5em 0.2em 0;
  font-size: var(--header-font-size);
  flex: 1 1 3em;
  min-width: 3em;
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
}
.disk-space {
  display: flex;
  align-items: center;
  cursor: default;
}
.pie-mini {
  width: 1.4em;
  height: 1.4em;
}
.disk-tooltip {
  line-height: 1.5;
}
.pie-tooltip {
  display: block;
}
.pie-tooltip .pie-label {
  fill: #fff;
  font-size: 9px;
}
</style>
