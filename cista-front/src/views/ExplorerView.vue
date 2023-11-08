<template>
  <FileExplorer
    ref="fileExplorer"
    :key="Router.currentRoute.value.path"
    :path="props.path"
    :documents="documents"
    v-if="props.path"
  />
</template>

<script setup lang="ts">
import { watchEffect, ref, computed } from 'vue'
import { useDocumentStore } from '@/stores/documents'
import Router from '@/router/index'
import { needleFormat, localeIncludes, collator } from '@/utils';

const documentStore = useDocumentStore()
const fileExplorer = ref()
const props = defineProps({
  path: Array<string>
})
const documents = computed(() => {
  if (!props.path) return []
  const loc = props.path.join('/')
  // List the current location
  if (!documentStore.search) return documentStore.document.filter(doc => doc.loc === loc)
  // Find up to 100 newest documents that match the search
  const search = documentStore.search
  const needle = needleFormat(search)
  let limit = 100
  let docs = []
  for (const doc of documentStore.recentDocuments) {
    if (localeIncludes(doc.haystack, needle)) {
      docs.push(doc)
      if (--limit === 0) break
    }
  }
  // Organize by folder, by relevance
  const locsub = loc + '/'
  docs.sort((a, b) => (
    // @ts-ignore
    (b.loc === loc) - (a.loc === loc) ||
    // @ts-ignore
    (b.loc.slice(0, locsub.length) === locsub) - (a.loc.slice(0, locsub.length) === locsub) ||
    collator.compare(a.loc, b.loc) ||
    // @ts-ignore
    (a.type === 'file') - (b.type === 'file') ||
    // @ts-ignore
    b.name.includes(search) - a.name.includes(search) ||
    collator.compare(a.name, b.name)
  ))
  return docs
})

watchEffect(() => {
  documentStore.fileExplorer = fileExplorer.value
})
</script>
