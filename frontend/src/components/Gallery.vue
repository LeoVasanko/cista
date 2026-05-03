<template>
  <div v-if="props.documents.length || editing" class="gallery" ref="gallery">
    <GalleryFigure v-if="editing?.key === 'new'" :doc="editing" :key=editing.key :editing="{rename: mkdir, exit}" />
    <template v-for="(doc, index) in documents" :key=doc.key>
      <BreadCrumb v-if="showFolderBreadcrumb(index)" :path="doc.loc ? doc.loc.split('/') : []" class="folder-indicator"/>
      <GalleryFigure
        :doc=doc
        :editing="editing === doc ? {rename, exit} : null"
        :style="{ '--gallery-figure-height': rowHeightsByKey[doc.key] ?? '15em' }"
        @menu="contextMenu($event, doc)"
        @rename="editing = doc; store.cursor = doc.key"
        :class="{ 'folder-start': showFolderBreadcrumb(index) }"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { apiFetch } from '@/repositories/Client'
import { Doc } from '@/repositories/Document'
import { useMainStore } from '@/stores/main'
import type { SortOrder } from '@/utils/docsort'
import ContextMenu from '@imengyu/vue3-context-menu'
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  shallowRef,
  watch,
  watchEffect
} from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{
  path: Array<string>
  documents: Doc[]
}>()
const store = useMainStore()
const router = useRouter()

const filesUrl = (path: string) =>
  '/files/' +
  path
    .split('/')
    .map(part => encodeURIComponent(part))
    .join('/')

const parseErrorMessage = async (res: Response) => {
  try {
    const data = await res.json()
    return data.message || data.detail || `${res.status} ${res.statusText}`
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

// File rename
const editing = shallowRef<Doc | null>(null)
const exit = () => {
  editing.value = null
}
const rename = async (doc: Doc, newName: string) => {
  const oldName = doc.name
  doc.name = newName // We should get an update from watch but this is quicker
  try {
    const dstUrl = doc.loc ? filesUrl(doc.loc) : '/files/'
    const res = await apiFetch(
      `${dstUrl}?mv=${doc.key}&to=${encodeURIComponent(newName)}`,
      { method: 'POST' }
    )
    if (!res.ok) throw new Error(await parseErrorMessage(res))
  } catch (err) {
    console.error('Rename failed', err)
    doc.name = oldName
    store.showToast(err instanceof Error ? err.message : 'Rename failed')
  }
}
const gallery = ref<HTMLElement>()
const columnCount = ref(1)
const columnWidthPx = ref(240)
const emPx = ref(16)
const aspectByKey = ref<Record<string, number>>({})

const optimalRowHeightPx = (ratios: number[]) => {
  const w = Math.max(1, columnWidthPx.value)
  const minH = Math.max(1, Math.round(7 * emPx.value))
  const maxH = Math.max(minH, Math.round(25 * emPx.value))
  const usable = ratios.filter(ar => Number.isFinite(ar) && ar > 0)
  if (usable.length === 0) return Math.round(15 * emPx.value)

  let bestH = Math.round(15 * emPx.value)
  let bestScore = -1
  for (let h = minH; h <= maxH; h++) {
    let score = 0
    for (const ar of usable) {
      let shownW = w
      let shownH = w * ar
      if (shownH > h) {
        shownH = h
        shownW = h / ar
      }
      // Fill efficiency in the row cell (0..1)
      score += (shownW * shownH) / (w * h)
    }
    if (score > bestScore) {
      bestScore = score
      bestH = h
    }
  }
  return bestH
}

const setAspect = (key: string, ar: number) => {
  if (!Number.isFinite(ar) || ar <= 0) return
  if (aspectByKey.value[key] === ar) return
  aspectByKey.value = {
    ...aspectByKey.value,
    [key]: ar
  }
}

const rowHeightsByKey = computed<Record<string, string>>(() => {
  const docs = props.documents
  const cols = Math.max(1, columnCount.value)
  const byKey = aspectByKey.value
  const out: Record<string, string> = {}

  const assignRows = (group: Doc[]) => {
    for (let start = 0; start < group.length; start += cols) {
      const row = group.slice(start, start + cols)
      const ratios = row
        .filter(doc => doc.previewable)
        .map(doc => byKey[doc.key])
        .filter((ar): ar is number => ar != null)
      const height = `${optimalRowHeightPx(ratios)}px`
      for (const doc of row) out[doc.key] = height
    }
  }

  let group: Doc[] = []
  for (let i = 0; i < docs.length; i++) {
    if (i > 0 && docs[i]!.loc !== docs[i - 1]!.loc) {
      assignRows(group)
      group = []
    }
    group.push(docs[i]!)
  }
  assignRows(group)

  return out
})

// Seed collected ratios from server-provided ar values on docs
const seedFromDocs = () => {
  for (const doc of props.documents)
    if (doc.previewable && doc.ar != null) setAspect(doc.key, doc.ar)
}

const onImgLoad = (e: Event) => {
  const img = e.target as HTMLImageElement
  if (img.tagName !== 'IMG' || img.naturalWidth === 0) return
  const anchor = img.closest('a[id^="file-"]') as HTMLAnchorElement | null
  if (!anchor) return
  const key = anchor.id.slice('file-'.length)
  if (!key) return
  setAspect(key, img.naturalHeight / img.naturalWidth)
}
const updateColumns = () => {
  if (!gallery.value) return
  const style = getComputedStyle(gallery.value)
  const templates = style.gridTemplateColumns
    .split(' ')
    .filter(part => !!part && part !== 'none')
  columnCount.value = Math.max(1, templates.length)
  const first = templates[0]
  if (first && first.endsWith('px')) {
    const parsed = Number.parseFloat(first)
    if (Number.isFinite(parsed) && parsed > 0) columnWidthPx.value = parsed
  }
  const parsedEm = Number.parseFloat(style.fontSize)
  if (Number.isFinite(parsedEm) && parsedEm > 0) emPx.value = parsedEm
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
      allocated: 0
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
        const a = document.querySelector(
          `#file-${store.cursor}`
        ) as HTMLAnchorElement | null
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
  up(ev: KeyboardEvent) {
    this.cursorMove(-columns.value, ev)
  },
  down(ev: KeyboardEvent) {
    this.cursorMove(columns.value, ev)
  },
  left(ev: KeyboardEvent) {
    this.cursorMove(-1, ev)
  },
  right(ev: KeyboardEvent) {
    this.cursorMove(1, ev)
  },
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
    const index = store.cursor ? docs.findIndex(doc => doc.key === store.cursor) : N
    // Stop navigation sideways away from the grid (only with up/down)
    if (ev && index === 0 && ev.key === 'ArrowLeft') return
    if (ev && index === N - 1 && ev.key === 'ArrowRight') return
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
        if (scrolltr) scrolltr.scrollIntoView({ block: 'center', behavior: 'smooth' })
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
  const el = document.querySelector(
    '.headermain input[type="search"]'
  ) as HTMLElement | null
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
  if (store.cursor && !editing.value) {
    const a = document.querySelector(
      `#file-${store.cursor}`
    ) as HTMLAnchorElement | null
    if (a) {
      a.focus()
      a.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
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
  seedFromDocs()
  if (gallery.value) {
    resizeObserver = new ResizeObserver(updateColumns)
    resizeObserver.observe(gallery.value)
    gallery.value.addEventListener('load', onImgLoad, { capture: true })
  }
})
onUnmounted(() => {
  resizeObserver?.disconnect()
  gallery.value?.removeEventListener('load', onImgLoad, { capture: true })
})

// Re-seed aspect ratios whenever docs update (e.g., ar patch from server)
watch(() => props.documents, seedFromDocs)
const mkdir = async (doc: Doc, name: string) => {
  doc.name = name
  doc.key = crypto.randomUUID()
  store.addGhost(doc)
  editing.value = null
  const path = doc.loc ? `${doc.loc}/${name}` : name
  try {
    const res = await apiFetch(filesUrl(path), { method: 'MKCOL' })
    if (!res.ok) throw new Error(await parseErrorMessage(res))
    router.push(doc.urlrouter)
  } catch (err) {
    console.error('Mkdir failed', err)
    store.showToast(err instanceof Error ? err.message : 'Mkdir failed')
  }
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
      await new Promise(r => (img.onload = r))
      const canvas = document.createElement('canvas')
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      canvas.getContext('2d')!.drawImage(img, 0, 0)
      const pngBlob = await new Promise<Blob>(r =>
        canvas.toBlob(b => r(b!), 'image/png')
      )
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

const deleteFile = async (doc: Doc) => {
  const path = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
  store.hideDoc(path)
  try {
    const res = await apiFetch(filesUrl(path), { method: 'DELETE' })
    if (!res.ok) throw new Error(await parseErrorMessage(res))
    store.showToast(`🗑️ Deleted ${doc.name}`)
  } catch (err) {
    console.error('Delete failed', err)
    store.unhideDoc(path)
    store.showToast(err instanceof Error ? err.message : 'Delete failed')
  }
}

const contextMenu = (ev: MouseEvent, doc: Doc) => {
  store.cursor = doc.key
  const items = [
    { label: '📥 Download', onClick: () => downloadFile(doc) },
    { label: '🔗 Copy Link', onClick: () => copyLink(doc) }
  ]
  if (doc.img) items.push({ label: '📋 Copy Image', onClick: () => copyImage(doc) })
  items.push(
    {
      label: '✏️ Rename',
      onClick: () => {
        editing.value = doc
      }
    },
    { label: '🗑️ Delete', onClick: () => deleteFile(doc) }
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
