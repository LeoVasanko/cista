<template>
  <div v-if="!props.path || documents.length === 0" class="empty-container">
    <component :is="cog" class="cog"/>
    <p v-if="!store.connected">No Connection</p>
    <p v-else-if="store.document.length === 0">Waiting for File List</p>
    <p v-else-if="store.query">No matches!</p>
    <p v-else-if="!store.document.some(doc => (doc.loc ? `${doc.loc}/${doc.name}` : doc.name) === props.path.join('/'))">Folder not found.</p>
    <p v-else>Empty folder</p>
  </div>
  <Gallery
    v-else-if="store.gallery"
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
  <div v-if="!store.gallery && documents.some(doc => doc.img)" class="suggest-gallery">
    <p>Media files found. Would you like a gallery view?</p>
    <SvgButton name="eye" taborder=0 @click="() => { store.gallery = true }">Gallery</SvgButton>
  </div>
</template>

<script setup lang="ts">
import { watchEffect, ref, computed } from 'vue'
import { useMainStore } from '@/stores/main'
import Router from '@/router/index'
import { needleFormat, localeIncludes, collator } from '@/utils'
import { sorted } from '@/utils/docsort'
import FileExplorer from '@/components/FileExplorer.vue'
import cog from '@/assets/svg/cog.svg'

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
  // Custom sort override in effect?
  const order = store.prefs.sortFiltered
  if (order) return sorted(docs, order)
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
</script>

<style scoped>
.empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 2rem;
  text-shadow: 0 0 1rem #000, 0 0 2rem #000;
  color: var(--accent-color);
}
@keyframes rotate {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(359deg); }
}
.suggest-gallery p {
  font-size: 2rem;
  color: var(--accent-color);
}
.suggest-gallery {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

svg.cog {
  width: 10rem;
  height: 10rem;
  margin: 0 auto;
  animation: rotate 10s linear infinite;
  filter: drop-shadow(0 0 1rem black);
  fill: var(--primary-color);
}
</style>
