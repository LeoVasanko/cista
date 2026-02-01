<template>
  <div v-if="store.toast" class="toast-message" @click="store.clearToast()">
    {{ store.toast }}
  </div>
  <div v-else-if="store.error && !store.authInProgress" class="toast-message status" @click="store.error = ''">
    {{ store.error }}
  </div>
  <SettingsModal />
  <UserManagementModal />
  <AccessDeniedModal />
  <header>
    <HeaderMain ref="headerMain" :path="path.pathList" :query="path.query" />
    <BreadCrumb :path="path.pathList" primary />
  </header>
  <main>
    <RouterView :path="path.pathList" :query="path.query" />
  </main>
  <footer v-if="store.selected.size || store.uprogress.total || store.dprogress.total">
    <HeaderSelected :path="path.pathList" />
    <TransferBar :status=store.uprogress @cancel=store.cancelUploads class=upload />
    <TransferBar :status=store.dprogress @cancel=store.cancelDownloads class=download />
  </footer>
</template>

<script setup lang="ts">
import { RouterView } from 'vue-router'
import type { ComputedRef } from 'vue'
import type HeaderMain from '@/components/HeaderMain.vue'
import { onMounted, onUnmounted, ref, watchEffect } from 'vue'
import { loadSession, watchConnect, watchDisconnect } from '@/repositories/WS'
import { useMainStore } from '@/stores/main'

import { computed } from 'vue'
import Router from '@/router/index'
import type { SortOrder } from './utils/docsort'
import type SettingsModalVue from './components/SettingsModal.vue'
import UserManagementModal from './components/UserManagementModal.vue'
import AccessDeniedModal from './components/AccessDeniedModal.vue'

interface Path {
  path: string
  pathList: string[]
  query: string
}
const store = useMainStore()
const path: ComputedRef<Path> = computed(() => {
  const p = decodeURIComponent(Router.currentRoute.value.path).split('//')
  const pathList = (p[0] ?? '').split('/').filter(value => value !== '')
  const query = p.slice(1).join('//')
  return {
    path: p[0] ?? '',
    pathList,
    query
  }
})
watchEffect(() => {
  document.title = path.value.path.replace(/\/$/, '').split('/').pop() || store.server.name || 'Cista Storage'
})
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
  const input = (event.target as HTMLElement).tagName === 'INPUT'
  const keyup = event.type === 'keyup'
  if (event.repeat) {
    if (
      event.key === 'ArrowUp' ||
      event.key === 'ArrowDown' ||
      event.key === 'ArrowLeft' ||
      event.key === 'ArrowRight' ||
      (c && event.code === 'Space')
    ) {
      if (!input) event.preventDefault()
    }
    return
  }
  //console.log("key pressed", event)
  /// Long if-else machina for all keys we handle here
  let arrow = ''
  if (!input && event.key.startsWith("Arrow")) arrow = event.key.slice(5).toLowerCase()
  // Find: process on keydown so that we can bypass the built-in search hotkey
  else if (!keyup && event.key === 'f' && (event.ctrlKey || event.metaKey)) {
    headerMain.value!.toggleSearchInput()
  }
  // Search also on / (UNIX style)
  else if (!input && keyup && event.key === '/') {
    headerMain.value!.toggleSearchInput()
  }
  // Globally close search, clear errors on Escape
  else if (keyup && event.key === 'Escape') {
    store.error = ''
    store.clearToast()
    headerMain.value!.clearSearch(event)
    store.focusBreadcrumb()
  }
  else if (!input && keyup && event.key === 'Backspace') {
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
    (event.code === 'Backquote' || event.key === '1' || event.key === '2' || event.key === '3')
  ) {
    store.sort(['', 'name', 'modified', 'size'][+event.key || 0] as SortOrder)
  }
  // Rename
  else if (!input && c && keyup && !event.ctrlKey && (event.key === 'F2' || event.key === 'r')) {
    fileExplorer.cursorRename()
  }
  // Toggle selections on file explorer; ignore all spaces to prevent scrolling built-in hotkey
  else if (!input && c && event.code === 'Space') {
    if (keyup && !event.altKey && !event.ctrlKey)
      fileExplorer.cursorSelect()
  }
  else return
  /// We are handling this!
  event.preventDefault()
  if (timer) {
    clearTimeout(timer) // Good for either timeout or interval
    timer = null
  }
  let f: any
  switch (arrow) {
    case 'up': f = () => fileExplorer.up(event); break
    case 'down': f = () => fileExplorer.down(event); break
    case 'left': f = () => fileExplorer.left(event); break
    case 'right': f = () => fileExplorer.right(event); break
  }
  if (f && !keyup) {
    // Initial move, then t0 delay until repeats at tr intervals
    const t0 = 200, tr = event.altKey ? 20 : 100
    f()
    timer = setTimeout(() => { timer = setInterval(f, tr) }, t0 - tr)
  }
}
onMounted(() => {
  window.addEventListener('keydown', globalShortcutHandler)
  window.addEventListener('keyup', globalShortcutHandler)
})
onUnmounted(() => {
  window.removeEventListener('keydown', globalShortcutHandler)
  window.removeEventListener('keyup', globalShortcutHandler)
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
