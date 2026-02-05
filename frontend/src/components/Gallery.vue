<template>
  <div v-if="props.documents.length || editing" class="gallery" ref="gallery">
    <GalleryFigure v-if="editing?.key === 'new'" :doc="editing" :key=editing.key :editing="{rename: mkdir, exit}" />
    <template v-for="(doc, index) in documents" :key=doc.key>
      <BreadCrumb v-if="showFolderBreadcrumb(index)" :path="doc.loc ? doc.loc.split('/') : []" class="folder-indicator"/>
      <GalleryFigure :doc=doc :editing="editing === doc ? {rename, exit} : null" @menu="contextMenu($event, doc)" :class="{ 'folder-start': showFolderBreadcrumb(index) }" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect, shallowRef, onMounted, onUnmounted, nextTick } from 'vue'
import { useMainStore } from '@/stores/main'
import { Doc } from '@/repositories/Document'
import { connect, controlUrl } from '@/repositories/WS'
import { useRouter } from 'vue-router'
import ContextMenu from '@imengyu/vue3-context-menu'
import type { SortOrder } from '@/utils/docsort'

const props = defineProps<{
  path: Array<string>
  documents: Doc[]
}>()
const store = useMainStore()
const router = useRouter()
// File rename
const editing = shallowRef<Doc | null>(null)
const exit = () => { editing.value = null }
const rename = (doc: Doc, newName: string) => {
  const oldName = doc.name
  const control = connect(controlUrl, {
    message(ev: MessageEvent) {
      const msg = JSON.parse(ev.data)
      if ('error' in msg) {
        console.error('Rename failed', msg.error.message, msg.error)
        doc.name = oldName
      } else {
        console.log('Rename succeeded', msg)
      }
    }
  })
  control.onopen = () => {
    control.send(
      JSON.stringify({
        op: 'rename',
        path: `${doc.loc}/${oldName}`,
        to: newName
      })
    )
  }
  doc.name = newName // We should get an update from watch but this is quicker
}
const gallery = ref<HTMLElement>()
const columnCount = ref(1)
const updateColumns = () => {
  if (!gallery.value) return
  columnCount.value = getComputedStyle(gallery.value).gridTemplateColumns.split(' ').length
}
const columns = computed(() => columnCount.value)
defineExpose({
  newFolder() {
    const now = Math.floor(Date.now() / 1000)
    editing.value = new Doc({
      loc: loc.value,
      key: 'new',
      name: 'New Folder',
      dir: true,
      mtime: now,
      size: 0,
      allocated: 0,
    })
    store.cursor = editing.value.key
  },
  toggleSelectAll() {
    console.log('Select')
    allSelected.value = !allSelected.value
  },
  toggleSortColumn(column: number) {
    const order = ['', 'name', 'modified', 'size', ''][column]
    if (order) store.toggleSort(order as SortOrder)
  },
  isCursor() {
    return store.cursor && editing.value === null
  },
  focusFirst() {
    const docs = props.documents
    if (docs.length > 0) {
      store.cursor = docs[0]!.key
      // Also focus the element directly (watchEffect won't trigger if cursor unchanged)
      nextTick(() => {
        const a = document.querySelector(`#file-${store.cursor}`) as HTMLAnchorElement | null
        if (a) a.focus()
      })
    }
  },
  cursorRename() {
    editing.value = props.documents.find(doc => doc.key === store.cursor) ?? null
  },
  cursorSelect() {
    const key = store.cursor
    if (!key) return
    if (store.selected.has(key)) {
      store.selected.delete(key)
    } else {
      store.selected.add(key)
    }
    this.cursorMove(1, null)
  },
  up(ev: KeyboardEvent) { this.cursorMove(-columns.value, ev) },
  down(ev: KeyboardEvent) { this.cursorMove(columns.value, ev) },
  left(ev: KeyboardEvent) { this.cursorMove(-1, ev) },
  right(ev: KeyboardEvent) { this.cursorMove(1, ev) },
  cursorMove(d: number, ev: KeyboardEvent | null) {
    const select = !!ev?.shiftKey
    // Move cursor up or down (keyboard navigation)
    const docs = props.documents
    if (docs.length === 0) {
      store.cursor = ''
      return
    }
    const N = docs.length
    const mod = (a: number, b: number) => ((a % b) + b) % b
    const increment = (i: number, d: number) => mod(i + d, N + 1)
    const index =
      store.cursor ? docs.findIndex(doc => doc.key === store.cursor) : N
    // Stop navigation sideways away from the grid (only with up/down)
    if (ev && index === 0 && ev.key === "ArrowLeft") return
    if (ev && index === N - 1 && ev.key === "ArrowRight") return
    // Calculate new position
    let moveto
    if (index === N) moveto = d > 0 ? 0 : N - 1
    else {
      moveto = increment(index, d)
      // Wrapping either end, just land outside the list
      if (Math.abs(d) >= N || Math.sign(d) !== Math.sign(moveto - index)) moveto = N
    }
    store.cursor = docs[moveto]?.key ?? ''
    const tr = store.cursor ? document.getElementById(`file-${store.cursor}`) : ''
    if (select) {
      // Go forwards, possibly wrapping over the end; the last entry is not toggled
      let [begin, end] = d > 0 ? [index, moveto] : [moveto, index]
      for (let p = begin; p !== end; p = increment(p, 1)) {
        if (p === N) continue
        const key = docs[p]!.key
        if (store.selected.has(key)) store.selected.delete(key)
        else store.selected.add(key)
      }
    }
    // @ts-ignore
    scrolltr = tr
    if (!scrolltimer) {
      scrolltimer = setTimeout(() => {
        if (scrolltr)
          scrolltr.scrollIntoView({ block: 'center', behavior: 'smooth' })
        scrolltimer = null
      }, 300)
    }
    // When leaving the file list: up goes to breadcrumbs, down goes to header
    if (moveto === N) {
      if (d < 0) focusBreadcrumb()
      else focusHeader()
    }
  }
})
const focusHeader = () => {
  const el = document.querySelector('.headermain input[type="search"]') as HTMLElement | null
  if (el) el.focus()
}
const focusBreadcrumb = () => {
  const el = document.querySelector('.breadcrumb') as HTMLElement | null
  if (el) el.focus()
}
let scrolltimer: any = null
let scrolltr: any = null
watchEffect(() => {
  if (store.cursor && store.cursor !== editing.value?.key) editing.value = null
  if (editing.value) store.cursor = editing.value.key
  if (store.cursor) {
    const a = document.querySelector(`#file-${store.cursor}`) as HTMLAnchorElement | null
    if (a) { a.focus(); a.scrollIntoView({ block: 'center', behavior: 'smooth' }) }
  }
})
watchEffect(() => {
  if (!props.documents.length && store.cursor && !store.query) {
    store.cursor = ''
    focusBreadcrumb()
  }
})
let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  const active = document.querySelector('.cursor') as HTMLElement | null
  if (active) {
    active.scrollIntoView({ block: 'center', behavior: 'instant' })
    active.focus()
  }
  updateColumns()
  if (gallery.value) {
    resizeObserver = new ResizeObserver(updateColumns)
    resizeObserver.observe(gallery.value)
  }
})
onUnmounted(() => {
  resizeObserver?.disconnect()
})
const mkdir = (doc: Doc, name: string) => {
  const control = connect(controlUrl, {
    open() {
      control.send(
        JSON.stringify({
          op: 'mkdir',
          path: `${doc.loc}/${name}`
        })
      )
    },
    message(ev: MessageEvent) {
      const msg = JSON.parse(ev.data)
      if ('error' in msg) {
        console.error('Mkdir failed', msg.error.message, msg.error)
        editing.value = null
      } else {
        console.log('mkdir', msg)
        router.push(doc.urlrouter)
      }
    }
  })
  doc.name = name
  doc.key = crypto.randomUUID()
  store.addGhost(doc)
  editing.value = null
}
const showFolderBreadcrumb = (i: number) => {
  const docs = props.documents
  const docloc = docs[i]!.loc
  return i === 0 ? docloc !== loc.value : docloc !== docs[i - 1]!.loc
}

const allSelected = computed({
  get: () => {
    return (
      props.documents.length > 0 &&
      props.documents.every((doc: Doc) => store.selected.has(doc.key))
    )
  },
  set: (value: boolean) => {
    console.log('Setting allSelected', value)
    for (const doc of props.documents) {
      if (value) {
        store.selected.add(doc.key)
      } else {
        store.selected.delete(doc.key)
      }
    }
  }
})

const loc = computed(() => props.path.join('/'))

const downloadFile = (doc: Doc) => {
  const path = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
  if (doc.dir) {
    // Download folder as ZIP
    const a = document.createElement('a')
    a.href = `/zip/${doc.key}/${doc.name}.zip`
    a.download = ''
    a.click()
    store.showToast(`Downloading ${doc.name}.zip`)
  } else {
    // Download single file
    const a = document.createElement('a')
    a.href = `/files/${path}`
    a.download = ''
    a.click()
    store.showToast(`Downloading ${doc.name}`)
  }
}

const copyLink = async (doc: Doc) => {
  const url = new URL(doc.url, window.location.origin).href
  try {
    await navigator.clipboard.writeText(url)
    store.showToast('📋 Link copied!')
  } catch {
    store.showToast('Failed to copy link')
  }
}

const copyImage = async (doc: Doc) => {
  const path = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
  try {
    store.showToast('Copying image...')
    const res = await fetch(`/files/${path}`)
    const blob = await res.blob()
    // Convert to PNG if needed (clipboard only supports PNG)
    if (blob.type !== 'image/png') {
      const img = new Image()
      img.src = URL.createObjectURL(blob)
      await new Promise(r => img.onload = r)
      const canvas = document.createElement('canvas')
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      canvas.getContext('2d')!.drawImage(img, 0, 0)
      const pngBlob = await new Promise<Blob>(r => canvas.toBlob(b => r(b!), 'image/png'))
      URL.revokeObjectURL(img.src)
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': pngBlob })])
    } else {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
    }
    store.showToast('📋 Image copied!')
  } catch (e) {
    console.error('Copy image failed', e)
    store.showToast('Failed to copy image')
  }
}

const deleteFile = (doc: Doc) => {
  const path = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
  store.hideDoc(path)
  const control = connect(controlUrl, {
    message(ev: MessageEvent) {
      const res = JSON.parse(ev.data)
      if ('error' in res) {
        console.error('Delete failed', res.error)
        store.unhideDoc(path)
        store.showToast(res.error.message || 'Delete failed')
      } else if (res.status === 'ack') {
        store.showToast(`🗑️ Deleted ${doc.name}`)
        control.close()
      }
    }
  })
  control.onopen = () => {
    control.send(JSON.stringify({ op: 'rm', sel: [path] }))
  }
}

const contextMenu = (ev: MouseEvent, doc: Doc) => {
  store.cursor = doc.key
  const items = [
    { label: '📥 Download', onClick: () => downloadFile(doc) },
    { label: '🔗 Copy Link', onClick: () => copyLink(doc) },
  ]
  if (doc.img) items.push({ label: '📋 Copy Image', onClick: () => copyImage(doc) })
  items.push(
    { label: '✏️ Rename', onClick: () => { editing.value = doc } },
    { label: '🗑️ Delete', onClick: () => deleteFile(doc) },
  )
  ContextMenu.showContextMenu({ x: ev.x, y: ev.y, items })
}
</script>

<style scoped>
.gallery {
  padding: 1em;
  width: 100%;
  display: grid;
  gap: .5em;
  grid-template-columns: repeat(auto-fill, minmax(15em, 1fr));
  align-items: end;
}
.folder-indicator {
  grid-column: 1 / -1;
}
.folder-start {
  grid-column-start: 1;
}
</style>
