<template>
  <Gallery
    v-if="store.prefs.gallery"
    ref="fileExplorer"
    :key="`gallery-${folderPath}`"
    :path="props.path"
    :documents="documents"
  />
  <FileExplorer
    v-else
    ref="fileExplorer"
    :key="`explorer-${folderPath}`"
    :path="props.path"
    :documents="documents"
  />
  <div v-if="store.searchLoading" class="search-loading">Searching...</div>
  <EmptyFolder :documents=documents :path=props.path />
</template>

<script setup lang="ts">
import { watchEffect, ref, computed, watch } from 'vue'
import { useMainStore } from '@/stores/main'
import { collator } from '@/utils'
import { sorted, sortedGrouped } from '@/utils/docsort'
import FileExplorer from '@/components/FileExplorer.vue'

const store = useMainStore()
const fileExplorer = ref()
const props = defineProps<{
  path: Array<string>
  query: string
}>()

// Folder path for component keys - only recreate component when folder changes, not search
const folderPath = computed(() => props.path.join('/'))

// Handle route-based search changes (back/forward navigation, direct URL)
// Skip if store.query already matches (means we triggered this via typing)
watch(
  () => [props.query, props.path.join('/')] as const,
  ([query, loc]) => {
    if (store.query === query) return  // Already searching this query
    store.search(query, loc)
  },
  { immediate: true }
)

const documents = computed(() => {
  const loc = props.path.join('/')
  const query = props.query

  // List the current location (no search)
  if (!query) return sorted(
    store.docsByLoc.get(loc) ?? [],
    store.prefs.sortListing,
  )

  // Search results from worker
  const docs = store.searchResults

  // Custom sort override in effect? Use grouped sorting to keep folders together
  const order = store.prefs.sortFiltered
  if (order) return sortedGrouped(docs, order)

  // Results are already sorted by relevance in the worker
  return docs
})

watchEffect(() => {
  store.fileExplorer = fileExplorer.value
})

// Only auto-switch gallery mode when entering a new folder or on initial file list load
watch([() => props.path.join('/'), () => store.document.length], ([path, len], [oldPath, oldLen]) => {
  // React to path change or initial document load (0 → non-zero)
  if (path === oldPath && oldLen !== undefined && oldLen > 0) return
  store.prefs.gallery = documents.value.some(d => d.previewable)
}, { immediate: true })
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
