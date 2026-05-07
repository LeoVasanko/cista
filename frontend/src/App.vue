<template>
  <div v-if="store.toast" class="toast-message" @click="store.clearToast()">
    {{ store.toast }}
  </div>
  <div v-else-if="store.error && !store.authInProgress" class="toast-message status" @click="store.error = ''">
    {{ store.error }}
  </div>
  <SettingsModal />
  <UserManagementModal />
  <UserTokensModal />
  <AboutModal />
  <AccessDeniedModal />
  <header>
    <HeaderMain
      ref="headerMain"
      :path="path.pathList"
      :query="path.query"
      :editor-mode="path.isEditorPath"
    />
    <BreadCrumb
      :path="path.breadcrumbPathList"
      :links="path.breadcrumbLinks"
      primary
    />
  </header>
  <main class="transition-wrapper">
    <RouterView v-slot="{ Component }">
      <Transition
        :name="routeTransitionName"
        @after-enter="store.transitionDirection = 'none'"
      >
        <KeepAlive>
          <component
            :is="Component"
            :key="routeViewKey"
            class="explorer-content"
            v-bind="routeViewProps"
          />
        </KeepAlive>
      </Transition>
    </RouterView>
  </main>
  <footer v-if="store.selected.size || store.uprogress.total || store.dprogress.total">
    <SelectionToolbar :path="path.pathList" />
    <TransferBar :status=store.uprogress @cancel=store.cancelUploads class=upload />
    <TransferBar :status=store.dprogress @cancel=store.cancelDownloads class=download />
  </footer>
</template>

<script setup lang="ts">
import type HeaderMain from '@/components/HeaderMain.vue'
import { loadSession, watchConnect, watchDisconnect } from '@/repositories/WS'
import { useMainStore } from '@/stores/main'
import type { ComputedRef } from 'vue'
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterView } from 'vue-router'

import Router from '@/router/index'
import { computed } from 'vue'
import AboutModal from './components/AboutModal.vue'
import AccessDeniedModal from './components/AccessDeniedModal.vue'
import SelectionToolbar from './components/SelectionToolbar.vue'
import type SettingsModalVue from './components/SettingsModal.vue'
import UserManagementModal from './components/UserManagementModal.vue'
import UserTokensModal from './components/UserTokensModal.vue'
import type { SortOrder } from './utils/docsort'

interface Path {
  path: string
  isEditorPath: boolean
  pathList: string[]
  breadcrumbPathList: string[]
  breadcrumbLinks?: string[]
  query: string
}
const store = useMainStore()
const path: ComputedRef<Path> = computed(() => {
  const p = decodeURIComponent(Router.currentRoute.value.path).split('//')
  const routePathList = (p[0] ?? '').split('/').filter(value => value !== '')
  const query = p.slice(1).join('//')
  const isEditorPath = routePathList[0] === 'edit'
  const pathList = isEditorPath ? routePathList.slice(1, -1) : routePathList
  const breadcrumbPathList = isEditorPath
    ? routePathList.slice(1)
    : routePathList
  const breadcrumbLinks = isEditorPath
    ? [
        '/',
        ...routePathList
          .slice(1, -1)
          .map((_, index) => `/${routePathList.slice(1, index + 2).join('/')}/`),
        `/${routePathList.join('/')}`
      ]
    : undefined
  return {
    path: p[0] ?? '',
    isEditorPath,
    pathList,
    breadcrumbPathList,
    breadcrumbLinks,
    query
  }
})
const routeTransitionName = computed(() => {
  if (store.transitionDirection === 'forward') return 'slide-forward'
  if (store.transitionDirection === 'backward') return 'slide-backward'
  return ''
})
const routeViewKey = computed(() => {
  const route = Router.currentRoute.value
  return route.name === 'editor' ? route.path : String(route.name ?? route.path)
})
const routeViewProps = computed(() =>
  path.value.isEditorPath
    ? {}
    : { path: path.value.pathList, query: path.value.query }
)
watch(
  () => path.value.path,
  () => {
    document.title =
      path.value.path.replace(/\/$/, '').split('/').pop() ||
      store.server.name ||
      'Cista Storage'
  },
  { immediate: true }
)
onMounted(loadSession)
onMounted(watchConnect)
onUnmounted(watchDisconnect)
const headerMain = ref<typeof HeaderMain | null>(null)
let vert = 0
let timer: any = null

const globalShortcutHandler = (event: KeyboardEvent) => {
  if (store.dialog) {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    return
  }
  const fileExplorer = store.fileExplorer as any
  if (!fileExplorer) return
  const c = fileExplorer.isCursor()
  const target = event.target as HTMLElement
  const input =
    ['INPUT', 'TEXTAREA'].includes(target.tagName) || !!target.closest('.cm-editor')
  const keyup = event.type === 'keyup'

  // Always clear repeat timer on arrow keyup, even if focus moved to input
  if (keyup && event.key.startsWith('Arrow') && timer) {
    clearTimeout(timer)
    timer = null
  }

  if (event.repeat) {
    if (
      event.key === 'ArrowUp' ||
      event.key === 'ArrowDown' ||
      event.key === 'ArrowLeft' ||
      event.key === 'ArrowRight' ||
      event.key === 'PageUp' ||
      event.key === 'PageDown' ||
      (c && event.code === 'Space')
    ) {
      if (!input) event.preventDefault()
    }
    return
  }
  //console.log("key pressed", event)
  /// Long if-else machina for all keys we handle here
  let arrow = ''
  let paging = ''
  const inHeader = !!(event.target as HTMLElement).closest('.headermain')
  const inBreadcrumb = !!(event.target as HTMLElement).closest('.breadcrumb')
  // Handle arrows: in search input with text, only up/down; otherwise all arrows
  const searchInput = inHeader && input
  const searchHasText = searchInput && (event.target as HTMLInputElement).value
  if (event.key.startsWith('Arrow')) {
    const dir = event.key.slice(5).toLowerCase()
    // In search with text: left/right move cursor, up/down navigate
    if (searchHasText && (dir === 'left' || dir === 'right')) {
      return // Let browser handle cursor movement
    }
    // Don't intercept arrows for non-search inputs (e.g. rename input)
    if (input && !searchInput) return
    arrow = dir
  } else if (
    event.key === 'PageUp' ||
    event.key === 'PageDown' ||
    event.key === 'Home' ||
    event.key === 'End'
  ) {
    if (input) return
    paging = event.key
  }
  if (arrow) {
    // Arrow key handling - fall through to bottom
  } else if (paging) {
    // Paging/navigation key handling - fall through to bottom
  }
  // Find: process on keydown so that we can bypass the built-in search hotkey
  else if (
    !path.value.isEditorPath &&
    !input &&
    !keyup &&
    event.key === 'f' &&
    (event.ctrlKey || event.metaKey)
  ) {
    headerMain.value!.toggleSearchInput()
  }
  // Search also on / (UNIX style) - use code to support any keyboard layout
  else if (!path.value.isEditorPath && !input && keyup && event.code === 'Slash') {
    // Record the actual character for display (varies by keyboard layout)
    if (event.key.length === 1 && event.key !== store.prefs.searchHotkey) {
      store.prefs.searchHotkey = event.key
    }
    headerMain.value!.toggleSearchInput()
  }
  // Globally close search, clear errors on Escape
  else if (keyup && event.key === 'Escape') {
    store.error = ''
    store.clearToast()
    // Keep rename and other non-search inputs isolated from search behavior.
    if (input && !searchInput) return
    if (!path.value.isEditorPath) {
      headerMain.value!.clearSearch(event)
    }
    store.focusBreadcrumb()
  } else if (!input && keyup && event.key === 'Backspace') {
    Router.back()
  }
  // Select all (toggle); keydown to precede and prevent builtin
  else if (!input && !keyup && event.key === 'a' && (event.ctrlKey || event.metaKey)) {
    fileExplorer.toggleSelectAll()
  }
  // G toggles Gallery
  else if (!input && keyup && event.key === 'g') {
    store.prefs.gallery = !store.prefs.gallery
  }
  // Keys Backquote-1-2-3 to sort columns
  else if (
    !input &&
    keyup &&
    (event.code === 'Backquote' ||
      event.key === '1' ||
      event.key === '2' ||
      event.key === '3')
  ) {
    store.sort(['', 'name', 'modified', 'size'][+event.key || 0] as SortOrder)
  }
  // Rename
  else if (
    !input &&
    c &&
    keyup &&
    !event.ctrlKey &&
    (event.key === 'F2' || event.key === 'r')
  ) {
    fileExplorer.cursorRename()
  }
  // Toggle selections on file explorer; ignore all spaces to prevent scrolling built-in hotkey
  else if (!input && c && event.code === 'Space') {
    if (keyup && !event.altKey && !event.ctrlKey) fileExplorer.cursorSelect()
  } else return
  /// We are handling this!
  event.preventDefault()
  if (timer) {
    clearTimeout(timer) // Good for either timeout or interval
    timer = null
  }
  let f: any
  // Arrow navigation - always use fileExplorer for repeatable movement
  if (arrow && !keyup) {
    const focusSearch = () =>
      (
        document.querySelector('.headermain input[type="search"]') as HTMLElement
      )?.focus()
    const focusBreadcrumb = () =>
      (document.querySelector('.breadcrumb') as HTMLElement)?.focus()

    if (inBreadcrumb) {
      // Breadcrumb: up→header (no repeat), down→files (with repeat)
      if (arrow === 'up') {
        focusSearch()
        f = null
      } else if (arrow === 'down') {
        fileExplorer.focusFirst?.()
        f = null
      }
    } else if (inHeader) {
      // Header: left/right navigate focusable items (buttons without tabindex=-1, search input, disk space)
      const items = Array.from(
        document.querySelectorAll(
          '.headermain button:not([tabindex="-1"]), .headermain input[type="search"], .headermain [tabindex="0"]'
        )
      ) as HTMLElement[]
      const idx = items.indexOf(document.activeElement as HTMLElement)
      if (arrow === 'left' && idx > 0) {
        items[idx - 1]?.focus()
        f = null
      } else if (arrow === 'right' && idx < items.length - 1) {
        items[idx + 1]?.focus()
        f = null
      } else if (arrow === 'up') f = () => fileExplorer.up({ shiftKey: false })
      else if (arrow === 'down') {
        focusBreadcrumb()
        f = null
      }
    } else {
      // File explorer: normal navigation with repeat
      switch (arrow) {
        case 'up':
          f = () => fileExplorer.up(event)
          break
        case 'down':
          f = () => fileExplorer.down(event)
          break
        case 'left':
          f = () => fileExplorer.left(event)
          break
        case 'right':
          f = () => fileExplorer.right(event)
          break
      }
    }
  } else if (paging && !keyup && !inHeader && !inBreadcrumb) {
    switch (paging) {
      case 'PageUp':
        f = () => fileExplorer.pageUp?.(event)
        break
      case 'PageDown':
        f = () => fileExplorer.pageDown?.(event)
        break
      case 'Home':
        f = () => fileExplorer.home?.(event)
        break
      case 'End':
        f = () => fileExplorer.end?.(event)
        break
    }
  }
  if (f) {
    // Initial move, then t0 delay until repeats at tr intervals
    const t0 = 200,
      tr = event.altKey ? 20 : 100
    f()
    if (paging === 'Home' || paging === 'End') return
    timer = setTimeout(() => {
      timer = setInterval(f, tr)
    }, t0 - tr)
  }
}
onMounted(() => {
  // Use capture phase to handle events before they reach target elements
  window.addEventListener('keydown', globalShortcutHandler, true)
  window.addEventListener('keyup', globalShortcutHandler, true)
})
onUnmounted(() => {
  window.removeEventListener('keydown', globalShortcutHandler, true)
  window.removeEventListener('keyup', globalShortcutHandler, true)
})
export type { Path }
</script>

<style>
/* Toast notifications - fixed at top center of viewport */
.toast-message {
  position: fixed;
  top: 1rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2000;
  padding: 0.75rem 1.5rem;
  background: var(--accent-color);
  color: #000;
  font-weight: bold;
  border-radius: 0.25rem;
  box-shadow: 0 0.25rem 1rem rgba(0, 0, 0, 0.3);
  cursor: pointer;
  max-width: 90vw;
  text-align: center;
}
.toast-message.status {
  background: #555;
  color: #fff;
}
footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(4px);
  z-index: 50;
}
footer > * {
  justify-content: center;
}
</style>
