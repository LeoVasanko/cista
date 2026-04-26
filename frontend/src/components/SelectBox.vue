<template>
  <input type=checkbox tabindex=-1 :checked="store.selected.has(doc.key)" @click.stop
    @change="ev => {
      if ((ev.target as HTMLInputElement).checked) {
        store.selected.add(doc.key)
      } else {
        store.selected.delete(doc.key)
      }
    }"
  >
</template>

<script setup lang="ts">
import type { Doc } from '@/repositories/Document'
import { useMainStore } from '@/stores/main'

const props = defineProps<{
  doc: Doc
}>()
const store = useMainStore()
</script>
