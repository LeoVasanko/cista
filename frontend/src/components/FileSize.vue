<template>
  <td
    class="size right"
    :class="sizeClass"
    @mouseenter="doc.sparseIndicator && tooltip?.startHover($event)"
    @mousemove="doc.sparseIndicator && tooltip?.updatePosition($event)"
    @mouseleave="doc.sparseIndicator && tooltip?.endHover()"
  >
    <SparseIndicator :doc="doc" class="before-size" />{{ doc.sizedisp }}
    <CursorTooltip v-if="doc.sparseIndicator" ref="tooltip" :text="tooltipText">{{ tooltipText }}</CursorTooltip>
  </td>
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { formatSize } from '@/utils'
import { computed, ref } from 'vue'
import CursorTooltip from './CursorTooltip.vue'
import SparseIndicator from './SparseIndicator.vue'

const props = defineProps<{
  doc: Doc
}>()

const tooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)

const sizeClass = computed(() => {
  const unit = props.doc.sizedisp.split('\u202F').slice(-1)[0]!
  return +unit ? 'bytes' : unit
})

const tooltipText = computed(() => {
  const { size, allocated } = props.doc
  return `${formatSize(allocated)} allocated of ${formatSize(size)}`
})
</script>

<style scoped>
.before-size {
  margin-right: 0.2em;
}
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
