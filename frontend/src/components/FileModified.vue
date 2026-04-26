<template>
  <td class="modified right">
    <time
      :datetime=datetime
      @mouseenter="tooltip?.startHover"
      @mousemove="tooltip?.updatePosition"
      @mouseleave="tooltip?.endHover"
    >{{ modified }}</time>
    <CursorTooltip ref="tooltip" :text="tooltipText">{{ tooltipText }}</CursorTooltip>
  </td>
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { formatUnixDate } from '@/utils'
import { computed, ref } from 'vue'
import CursorTooltip from './CursorTooltip.vue'

const props = defineProps<{
  doc: Doc
  now: number
}>()

const tooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)

// Reference props.now to trigger reactivity when time updates
const modified = computed(() => {
  props.now // trigger reactivity
  return formatUnixDate(props.doc.mtime)
})

const datetime = computed(() =>
  new Date(1000 * props.doc.mtime).toISOString().replace('.000Z', 'Z')
)

const tooltipText = computed(() =>
  datetime.value.replace('T', ' ').replace('Z', ' UTC')
)
</script>
