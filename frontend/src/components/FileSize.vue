<template>
  <td class="size right" :class=sizeClass>{{ doc.sizedisp }}</td>
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { computed } from 'vue'

const sizeClass = computed(() => {
  const unit = props.doc.sizedisp.split('\u202F').slice(-1)[0]!
  return +unit ? "bytes" : unit
})

const props = defineProps<{
    doc: Doc
}>()
</script>

<style scoped>
.size.empty { color: #555 }
.size.bytes { color: #77a }
.size.kB { color: #474 }
.size.MB { color: #a80 }
.size.GB { color: #f83 }
.size.TB, .size.PB, .size.EB, .size.huge {
  color: #f44;
  text-shadow: 0 0 .2em;
}

@media (prefers-color-scheme: dark) {
  .size.empty { color: #bbb }
  .size.bytes { color: #99d }
  .size.kB { color: #aea }
  .size.MB { color: #ff4 }
  .size.GB { color: #f86 }
  .size.TB, .size.PB, .size.EB, .size.huge { color: #f55 }
}

.cursor .size {
  color: inherit;
  text-shadow: none;
}
</style>
