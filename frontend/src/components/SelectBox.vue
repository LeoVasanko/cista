<template>
  <input type=checkbox tabindex=-1 :checked="store.selected.has(doc.key)"
    @change="ev => {
      if ((ev.target as HTMLInputElement).checked) {
        store.selected.add(doc.key)
      } else {
        store.selected.delete(doc.key)
      }
    }"
  >
</template>

<script setup lang=ts>
import { defineProps } from 'vue'
import { useMainStore } from '@/stores/main'
import type { Doc } from '@/repositories/Document'

const props = defineProps<{
  doc: Doc
}>()
const store = useMainStore()

</script>
