<template>
  <LoginModal />
  <header>
    <HeaderMain ref="headerMain" :path="path.pathList" :query="path.query">
      <HeaderSelected :path="path.pathList" />
    </HeaderMain>
    <BreadCrumb :path="path.pathList" tabindex="-1"/>
  </header>
  <main>
    <RouterView :path="path.pathList" :query="path.query" />
  </main>
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

interface Path {
  path: string
  pathList: string[]
  query: string
}
const store = useMainStore()
const path: ComputedRef<Path> = computed(() => {
  const p = decodeURIComponent(Router.currentRoute.value.path).split('//')
  const pathList = p[0].split('/').filter(value => value !== '')
  const query = p.slice(1).join('//')
  return {
    path: p[0],
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
  const fileExplorer = store.fileExplorer as any
  if (!fileExplorer) return
  const c = fileExplorer.isCursor()
  const keyup = event.type === 'keyup'
  if (event.repeat) {
    if (
      event.key === 'ArrowUp' ||
      event.key === 'ArrowDown' ||
      (c && event.code === 'Space')
    ) {
      event.preventDefault()
    }
    return
  }
  //console.log("key pressed", event)
  // For up/down implement custom fast repeat
  if (event.key === 'ArrowUp') vert = keyup ? 0 : event.altKey ? -10 : -1
  else if (event.key === 'ArrowDown') vert = keyup ? 0 : event.altKey ? 10 : 1
  // Find: process on keydown so that we can bypass the built-in search hotkey
  else if (!keyup && event.key === 'f' && (event.ctrlKey || event.metaKey)) {
    headerMain.value!.toggleSearchInput()
  }
  // Select all (toggle); keydown to prevent builtin
  else if (!keyup && event.key === 'a' && (event.ctrlKey || event.metaKey)) {
    fileExplorer.toggleSelectAll()
  }
  // Keys 1-3 to sort columns
  else if (
    c &&
    keyup &&
    (event.key === '1' || event.key === '2' || event.key === '3')
  ) {
    fileExplorer.toggleSortColumn(+event.key)
  }
  // Rename
  else if (c && keyup && !event.ctrlKey && (event.key === 'F2' || event.key === 'r')) {
    fileExplorer.cursorRename()
  }
  // Toggle selections on file explorer; ignore all spaces to prevent scrolling built-in hotkey
  else if (c && event.code === 'Space') {
    if (keyup && !event.altKey && !event.ctrlKey)
      fileExplorer.cursorSelect()
  } else return
  event.preventDefault()
  if (!vert) {
    if (timer) {
      clearTimeout(timer) // Good for either timeout or interval
      timer = null
    }
    return
  }
  if (!timer) {
    // Initial move, then t0 delay until repeats at tr intervals
    const select = event.shiftKey
    fileExplorer.cursorMove(vert, select)
    const t0 = 200,
      tr = 30
    timer = setTimeout(
      () =>
        (timer = setInterval(() => {
          fileExplorer.cursorMove(vert, select)
        }, tr)),
      t0 - tr
    )
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
@/stores/main
