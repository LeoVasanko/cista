<template>
  <td class="modified right">
    <time
      :datetime=datetime
      @mouseenter="startHover"
      @mousemove="updatePosition"
      @mouseleave="endHover"
    >{{ modified }}</time>
    <Teleport to="body">
      <div v-if="showTooltip" class="cursor-tooltip" :style="tooltipStyle">
        {{ tooltipText }}
      </div>
    </Teleport>
  </td>
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { formatUnixDate } from '@/utils'
import { computed, ref } from 'vue'

const props = defineProps<{
    doc: Doc
    now: number
}>()

// Reference props.now to trigger reactivity when time updates
const modified = computed(() => {
  props.now  // trigger reactivity
  return formatUnixDate(props.doc.mtime)
})

const datetime = computed(() =>
  new Date(1000 * props.doc.mtime).toISOString().replace('.000Z', 'Z')
)

const tooltipText = computed(() =>
  datetime.value.replace('T', ' ').replace('Z', ' UTC')
)

const showTooltip = ref(false)
const mouseX = ref(0)
const mouseY = ref(0)
let hoverTimer: ReturnType<typeof setTimeout> | null = null

const tooltipStyle = computed(() => ({
  left: `${mouseX.value + 12}px`,
  top: `${mouseY.value + 12}px`,
}))

const startHover = (e: MouseEvent) => {
  mouseX.value = e.clientX
  mouseY.value = e.clientY
  hoverTimer = setTimeout(() => {
    showTooltip.value = true
  }, 500)
}

const updatePosition = (e: MouseEvent) => {
  mouseX.value = e.clientX
  mouseY.value = e.clientY
}

const endHover = () => {
  if (hoverTimer) {
    clearTimeout(hoverTimer)
    hoverTimer = null
  }
  showTooltip.value = false
}
</script>

<style scoped>
.cursor-tooltip {
  position: fixed;
  z-index: 10000;
  padding: .5rem 1rem;
  border-radius: 3rem 0 3rem 0;
  box-shadow: 0 0 1rem var(--accent-color);
  background-color: var(--accent-color);
  color: var(--primary-color);
  white-space: pre;
  pointer-events: none;
  font-size: 1rem;
}
</style>
