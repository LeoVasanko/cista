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
import { useMainStore } from '@/stores/main'
import Router from '@/router/index'
import { needleFormat, localeIncludes, collator } from '@/utils';

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
  if (!query) return store.document.filter(doc => doc.loc === loc)
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
    b.name.includes(query) - a.name.includes(query) ||
    collator.compare(a.name, b.name)
  ))
  return docs
})

watchEffect(() => {
  store.fileExplorer = fileExplorer.value
})
</script>
