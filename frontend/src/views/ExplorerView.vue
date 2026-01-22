<template>
  <Gallery
    v-if="store.prefs.gallery"
    ref="fileExplorer"
    :key="`gallery-${Router.currentRoute.value.path}`"
    :path="props.path"
    :documents="documents"
  />
  <FileExplorer
    v-else
    ref="fileExplorer"
    :key="`explorer-${Router.currentRoute.value.path}`"
    :path="props.path"
    :documents="documents"
  />
  <EmptyFolder :documents=documents :path=props.path />
</template>

<script setup lang="ts">
import { watchEffect, ref, computed, watch } from 'vue'
import { useMainStore } from '@/stores/main'
import Router from '@/router/index'
import { needleFormat, localeIncludes, collator } from '@/utils'
import { sorted, sortedGrouped } from '@/utils/docsort'
import FileExplorer from '@/components/FileExplorer.vue'

const store = useMainStore()
const fileExplorer = ref()
const props = defineProps<{
  path: Array<string>
  query: string
}>()
const documents = computed(() => {
  const loc = props.path.join('/')
  const query = props.query
  // List the current location
  if (!query) return sorted(
    store.document.filter(doc => doc.loc === loc),
    store.prefs.sortListing,
  )
  // Find up to 100 newest documents that match the search
  const needle = needleFormat(query)
  let limit = 100
  let docs = []
  for (const doc of store.recentDocuments) {
    if (localeIncludes(doc.haystack, needle)) {
      docs.push(doc)
      if (--limit === 0) break
    }
  }
  const locsub = loc + '/'
  // Custom sort override in effect? Use grouped sorting to keep folders together
  const order = store.prefs.sortFiltered
  if (order) return sortedGrouped(docs, order)
  // Sort by relevance - current folder, then subfolders, then others
  docs.sort((a, b) => (
    // @ts-ignore
    (b.loc === loc) - (a.loc === loc) ||
    // @ts-ignore
    (b.loc.slice(0, locsub.length) === locsub) - (a.loc.slice(0, locsub.length) === locsub) ||
    collator.compare(a.loc, b.loc) ||
    // @ts-ignore
    (a.type === 'file') - (b.type === 'file') ||
    // @ts-ignore
    b.name.includes(query) - a.name.includes(query) ||
    collator.compare(a.name, b.name)
  ))
  return docs
})

watchEffect(() => {
  store.fileExplorer = fileExplorer.value
  store.query = props.query
})

watch([() => props.path.join('/'), () => props.query], () => {
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
</style>
