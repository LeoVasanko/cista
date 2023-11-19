<template>
  <div v-if="props.documents.length || editing" class="gallery" ref="gallery">
    <GalleryFigure v-for="(doc, index) in documents" :key="doc.key" :doc="doc" :index="index">
      <BreadCrumb :path="doc.loc ? doc.loc.split('/') : []" v-if="showFolderBreadcrumb(index)" class="folder-change"/>
    </GalleryFigure>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect, shallowRef, onMounted, onUnmounted, nextTick } from 'vue'
import { useMainStore } from '@/stores/main'
import { Doc } from '@/repositories/Document'
import FileRenameInput from './FileRenameInput.vue'
import { connect, controlUrl } from '@/repositories/WS'
import { formatSize } from '@/utils'
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
const columns = computed(() => {
  if (!gallery.value) return 1
  return getComputedStyle(gallery.value).gridTemplateColumns.split(' ').length
})
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
    })
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
    let moveto
    if (index === N) moveto = d > 0 ? 0 : N - 1
    else {
      moveto = increment(index, d)
      // Wrapping either end, just land outside the list
      if (Math.abs(d) >= N || Math.sign(d) !== Math.sign(moveto - index)) moveto = N
    }
    console.log("Gallery cursorMove", d, index, moveto, moveto - index)
    store.cursor = docs[moveto]?.key ?? ''
    const tr = store.cursor ? document.getElementById(`file-${store.cursor}`) : ''
    if (select) {
      // Go forwards, possibly wrapping over the end; the last entry is not toggled
      let [begin, end] = d > 0 ? [index, moveto] : [moveto, index]
      for (let p = begin; p !== end; p = increment(p, 1)) {
        if (p === N) continue
        const key = docs[p].key
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
    if (moveto === N) focusBreadcrumb()
  }
})
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
  if (!props.documents.length && store.cursor) {
    store.cursor = ''
    focusBreadcrumb()
  }
})
let nowkey = ref(0)
let modifiedTimer: any = null
const updateModified = () => {
  nowkey.value = Math.floor(Date.now() / 1000)
}
onMounted(() => { updateModified(); modifiedTimer = setInterval(updateModified, 1000) })
onUnmounted(() => { clearInterval(modifiedTimer) })
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
  // We should get an update from watch but this is quicker
  doc.name = name
  doc.key = crypto.randomUUID()
}
const showFolderBreadcrumb = (i: number) => {
  const docs = props.documents
  const docloc = docs[i].loc
  return i === 0 ? docloc !== loc.value : docloc !== docs[i - 1].loc
}
const selectionIndeterminate = computed({
  get: () => {
    return (
      props.documents.length > 0 &&
      props.documents.some((doc: Doc) => store.selected.has(doc.key)) &&
      !allSelected.value
    )
  },
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  set: (value: boolean) => {}
})
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

const contextMenu = (ev: MouseEvent, doc: Doc) => {
  store.cursor = doc.key
  ContextMenu.showContextMenu({
    x: ev.x, y: ev.y, items: [
      { label: 'Rename', onClick: () => { editing.value = doc } },
    ],
  })
}
</script>

<style scoped>
.gallery {
  padding: 1rem;
  width: 100%;
  display: grid;
  gap: .5rem;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  grid-auto-rows: 15rem;
}
.breadcrumb {
  position: absolute;
  z-index: 1;
}
</style>
