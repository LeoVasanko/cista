<template>
  <div class="transition-wrapper">
    <Transition
      :name="transitionName"
      @after-enter="onAfterEnter"
    >
      <KeepAlive>
        <component
          :is="store.prefs.gallery ? Gallery : FileExplorer"
          :key="cacheKey"
          ref="fileExplorer"
          class="explorer-content"
          :path="props.path"
          :documents="documents"
        />
      </KeepAlive>
    </Transition>
    <EmptyFolder :documents="documents" :path="props.path" />
  </div>
  <div v-if="store.searchLoading" class="search-loading">Searching...</div>
</template>

<script setup lang="ts">
import FileExplorer from '@/components/FileExplorer.vue'
import Gallery from '@/components/Gallery.vue'
import { getDocuments } from '@/stores/documentStore'
import { useMainStore } from '@/stores/main'
import { collator } from '@/utils'
import { sorted, sortedGrouped } from '@/utils/docsort'
import { computed, nextTick, ref, watch, watchEffect } from 'vue'

const store = useMainStore()
const fileExplorer = ref()
const props = defineProps<{
  path: Array<string>
  query: string
}>()

// Folder path for component keys - only recreate component when folder changes, not search
const folderPath = computed(() => props.path.join('/'))
const cacheKey = computed(() => `${store.prefs.gallery ? 'gallery' : 'list'}:${folderPath.value}`)

const transitionName = computed(() => {
  if (store.transitionDirection === 'forward') return 'slide-forward'
  if (store.transitionDirection === 'backward') return 'slide-backward'
  return ''
})

const folderScrollTop = new Map<string, number>()
const scrollKey = (path: string) => path || '/'
const getMainScroller = () => document.querySelector('main') as HTMLElement | null

const restoreScroll = (path: string) => {
  const scroller = getMainScroller()
  if (!scroller) return
  const top = folderScrollTop.get(scrollKey(path)) ?? 0
  scroller.scrollTop = top
}

const onAfterEnter = () => {
  store.transitionDirection = 'none'
  restoreScroll(folderPath.value)
}

// Handle route-based search changes (back/forward navigation, direct URL)
// Skip if store.query already matches (means we triggered this via typing)
watch(
  () => [props.query, props.path.join('/')] as const,
  ([query, loc]) => {
    if (store.query === query) return // Already searching this query
    store.search(query, loc)
  },
  { immediate: true }
)

const documents = computed(() => {
  const loc = props.path.join('/')
  const query = props.query

  // List the current location (no search)
  if (!query) {
    // Access docVersion to make this reactive to document changes
    void store.docVersion
    const hidden = store.hiddenPaths
    const docs = getDocuments().filter(
      doc =>
        doc.loc === loc && !hidden.has(doc.loc ? `${doc.loc}/${doc.name}` : doc.name)
    )
    // Overlay ghosts for this location (excluding hidden ones)
    const ghosts = store.ghosts.filter(
      g => g.loc === loc && !hidden.has(g.loc ? `${g.loc}/${g.name}` : g.name)
    )
    // Merge: ghosts that don't conflict with real docs
    const realNames = new Set(docs.map(d => d.name))
    const merged = [...docs, ...ghosts.filter(g => !realNames.has(g.name))]
    return sorted(merged, store.prefs.sortListing)
  }

  // Search results from worker (also filter hidden)
  const hidden = store.hiddenPaths
  const docs = store.searchResults.filter(
    doc => !hidden.has(doc.loc ? `${doc.loc}/${doc.name}` : doc.name)
  )

  // Custom sort override in effect? Use grouped sorting to keep folders together
  const order = store.prefs.sortFiltered
  if (order) return sortedGrouped(docs, order)

  // Results are already sorted by relevance in the worker
  return docs
})

watchEffect(() => {
  store.fileExplorer = fileExplorer.value
})

watch(
  folderPath,
  async (path, oldPath) => {
    const scroller = getMainScroller()
    if (scroller && oldPath !== undefined) {
      folderScrollTop.set(scrollKey(oldPath), scroller.scrollTop)
    }
    await nextTick()
    requestAnimationFrame(() => restoreScroll(path))
  },
  { immediate: true }
)

// Only auto-switch gallery mode when entering a new folder or on initial file list load
watch(
  [() => props.path.join('/'), () => store.documentCount],
  ([path, len], [oldPath, oldLen]) => {
    // React to path change or initial document load (0 → non-zero)
    if (path === oldPath && oldLen !== undefined && oldLen > 0) return
    store.prefs.gallery = documents.value.some(d => d.previewable)
  },
  { immediate: true }
)
</script>

<style scoped>
.empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 2rem;
  text-shadow: 0 0 .3rem #000, 0 0 2rem #0008;
  color: var(--accent-color);
}
.search-loading {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  padding: 0.5rem 1rem;
  background: var(--accent-color, #007bff);
  color: white;
  border-radius: 0.25rem;
  font-size: 0.875rem;
  opacity: 0.9;
}
</style>
