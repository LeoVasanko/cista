<template>
  <Teleport to="body">
    <div v-if="visible" class="cursor-tooltip" :style="tooltipStyle">
      <slot></slot>
    </div>
  </Teleport>
</template>

<script lang="ts">
// Global activation state - shared across all instances
let globalActive = false
let globalDeactivateTimer: ReturnType<typeof setTimeout> | null = null
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  text: string
  delay?: number
}>()

const visible = ref(false)
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
  // Clear any pending deactivation
  if (globalDeactivateTimer) {
    clearTimeout(globalDeactivateTimer)
    globalDeactivateTimer = null
  }
  const delay = globalActive ? 0 : (props.delay ?? 800)
  hoverTimer = setTimeout(() => {
    visible.value = true
    globalActive = true
  }, delay)
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
  visible.value = false
  // Deactivate global state after a short delay if no new tooltip started
  if (globalDeactivateTimer) clearTimeout(globalDeactivateTimer)
  globalDeactivateTimer = setTimeout(() => {
    globalActive = false
  }, 500)
}

defineExpose({
  startHover,
  updatePosition,
  endHover,
})
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
  white-space: nowrap;
  pointer-events: none;
  font-size: 1rem;
}
</style>
