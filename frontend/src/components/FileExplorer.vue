<template>
  <table v-if="props.documents.length || editing">
    <thead>
      <tr>
        <th class="selection">
          <input type="checkbox" tabindex="-1" v-model="allSelected" :indeterminate="selectionIndeterminate">
        </th>
        <th class="sortcolumn" :class="{ sortactive: store.sortOrder === 'name' }" @click="store.toggleSort('name')">Name</th>
        <th class="sortcolumn modified right" :class="{ sortactive: store.sortOrder === 'modified' }" @click="store.toggleSort('modified')">Modified</th>
        <th class="sortcolumn size right" :class="{ sortactive: store.sortOrder === 'size' }" @click="store.toggleSort('size')">Size</th>
        <th class="menu"></th>
      </tr>
    </thead>
    <tbody>
      <tr v-if="editing?.key === 'new'" class="folder">
        <td class="selection"></td>
        <td class="name">
          <FileRenameInput :doc="editing" :rename="mkdir" :exit="() => {editing = null}" />
        </td>
        <FileModified :doc=editing :now=nowkey />
        <FileSize :doc=editing />
        <td class="menu"></td>
      </tr>
      <template v-for="(doc, index) in documents" :key="doc.key">
        <tr class="folder-change" v-if="showFolderBreadcrumb(index)">
          <th colspan="5"><BreadCrumb :path="doc.loc ? doc.loc.split('/') : []" /></th>
        </tr>

        <tr
          :id="`file-${doc.key}`"
          :class="{ file: !doc.dir, folder: doc.dir, cursor: store.cursor === doc.key }"
          @click="store.cursor = store.cursor === doc.key ? '' : doc.key"
          @contextmenu.prevent="contextMenu($event, doc)"
        >
          <td class="selection" @click.up.stop="store.cursor = store.cursor === doc.key ? doc.key : ''">
            <input
              type="checkbox"
              tabindex="-1"
              :checked="store.selected.has(doc.key)"
              @change="
                ($event.target as HTMLInputElement).checked
                  ? store.selected.add(doc.key)
                  : store.selected.delete(doc.key)
              "
            />
          </td>
          <td class="name">
            <template v-if="editing === doc">
              <FileRenameInput :doc="doc" :rename="rename" :exit="() => {editing = null}" />
            </template>
            <template v-else>
              <a :href=doc.url tabindex=-1 @contextmenu.stop @focus.stop="store.cursor = doc.key">
                {{ doc.name }}
              </a>
              <button tabindex=-1 v-if="store.cursor == doc.key" class="rename-button" @click="() => (editing = doc)">🖊️</button>
            </template>
          </td>
          <FileModified :doc=doc :now=nowkey />
          <FileSize :doc=doc />
          <td class="menu">
            <button tabindex=-1 @click.stop="contextMenu($event, doc)">⋮</button>
          </td>
        </tr>
      </template>
      <tr class="summary" v-if="props.documents.length > 1">
        <td colspan="3" class="right">{{props.documents.length}} items</td>
        <td class="size right">{{ formatSize(props.documents.reduce((a, b) => a + b.size, 0)) }}</td>
        <td class="menu"></td>
      </tr>
    </tbody>
  </table>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect, shallowRef, onMounted, onUnmounted } from 'vue'
import { useMainStore } from '@/stores/main'
import { Doc } from '@/repositories/Document'
import FileRenameInput from './FileRenameInput.vue'
import { connect, controlUrl } from '@/repositories/WS'
import { formatSize } from '@/utils'
import { useRouter } from 'vue-router'
import ContextMenu from '@imengyu/vue3-context-menu'

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
defineExpose({
  newFolder() {
    console.log("New folder")
    const now = Math.floor(Date.now() / 1000)
    editing.value = new Doc({
      loc: loc.value,
      key: 'new',
      name: 'New Folder',
      dir: true,
      mtime: now,
      size: 0,
    })
    store.cursor = editing.value.key
  },
  toggleSelectAll() {
    console.log('Select')
    allSelected.value = !allSelected.value
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
  up(ev: KeyboardEvent) { this.cursorMove(-1, ev) },
  down(ev: KeyboardEvent) { this.cursorMove(1, ev) },
  left(ev: KeyboardEvent) { router.back() },
  right(ev: KeyboardEvent) {
    const a = document.querySelector(`#file-${store.cursor} a`) as HTMLAnchorElement | null
    if (a) a.click()
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
    const index =
      store.cursor ? docs.findIndex(doc => doc.key === store.cursor) : docs.length
    const moveto = increment(index, d)
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
  if (editing.value) store.cursor = editing.value?.key
  if (store.cursor) {
    const a = document.querySelector(
      `#file-${store.cursor} .name a`
    ) as HTMLAnchorElement | null
    if (a) a.focus()
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
onMounted(() => {
  updateModified(); modifiedTimer = setInterval(updateModified, 1000)
  const active = document.querySelector('.cursor') as HTMLElement | null
  if (active) {
    active.scrollIntoView({ block: 'center', behavior: 'instant' })
    active.focus()
  }
})
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
table {
  width: 100%;
  table-layout: fixed;
}
thead tr {
  position: sticky;
  top: 0;
  z-index: 2;
}
tbody tr {
  position: relative;
  z-index: auto;
}
table thead .selection input[type='checkbox'] {
  position: inherit;
  width: 1rem;
  height: 1rem;
  padding: 0;
  margin: auto;
}
table tbody .selection input[type='checkbox'] {
  width: 2rem;
  height: 2rem;
}
table .selection {
  width: 3rem;
  text-align: center;
  text-overflow: clip;
  padding: 0;
}
table .selection input {
  margin: auto;
}
table .modified {
  width: 10rem;
  text-overflow: clip;
}
table .size {
  width: 7rem;
  text-overflow: clip;
}
table .menu {
  width: 2rem;
}
tbody td {
  font-size: 1.2rem;
}
table th,
table td {
  padding: 0 0.5rem;
  font-weight: normal;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.name {
  white-space: nowrap;
  position: relative;
}
.name .rename-button {
  position: absolute;
  right: 0;
  animation: appear calc(5 * var(--transition-time)) linear;
}
@keyframes appear {
  from {
    opacity: 0;
  }
  80% {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
thead tr {
  font-size: 0.8rem;
  background: linear-gradient(to bottom, #eee, #fff 30%, #ddd);
  color: #000;
  box-shadow: 0 0 .2rem black;
}
tbody tr.cursor {
  background: var(--accent-color);
}
.right {
  text-align: right;
}
.sortcolumn:hover {
  cursor: pointer;
}
.sortcolumn:hover::after {
  color: var(--accent-color);
}
.sortcolumn {
  padding-right: 1.5rem;
}
.sortcolumn::after {
  font-size: 1rem;
  content: '▸';
  color: #888;
  margin-left: 0.5rem;
  margin-top: -.2rem;
  position: absolute;
  transition: all var(--transition-time) linear;
}
.sortactive::after {
  transform: rotate(90deg);
  color: var(--accent-color);
}
.name a {
  text-decoration: none;
}
tbody .selection input {
  z-index: 1;
  position: absolute;
  opacity: 0;
  left: 0.5rem;
  top: 0;
}
.selection {
  width: 2em;
  height: 2em;
}
.selection input:checked {
  opacity: 0.7;
}
.file .selection::before {
  content: '📄';
  font-size: 1.5rem;
}
.folder .selection::before {
  height: 2rem;
  content: '📁';
  font-size: 1.5rem;
}
.empty-container {
  padding-top: 3rem;
  text-align: center;
  font-size: 3rem;
  color: var(--accent-color);
}
.folder-change {
  margin-left: -.5rem;
}
.loc {
  color: #888;
}
.summary {
  color: #888;
}
</style>
@/stores/main
