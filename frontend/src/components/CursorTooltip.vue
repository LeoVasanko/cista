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
// Track if we've seen real mouse movement (not touch-simulated)
let hasRealMouse = false
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
let settleTimer: ReturnType<typeof setTimeout> | null = null
let lastMoveX = 0
let lastMoveY = 0

// Movement threshold (pixels) - cursor must settle within this radius
const SETTLE_THRESHOLD = 8

const tooltipStyle = computed(() => ({
  left: `${mouseX.value}px`,
  top: `${mouseY.value}px`,
}))

// Check if the device likely has a real mouse (fine pointer)
const hasFinePointer = () => window.matchMedia('(pointer: fine)').matches

const showTooltip = () => {
  visible.value = true
  globalActive = true
}

const scheduleTooltip = () => {
  if (settleTimer) clearTimeout(settleTimer)
  if (globalDeactivateTimer) {
    clearTimeout(globalDeactivateTimer)
    globalDeactivateTimer = null
  }
  const delay = globalActive ? 0 : (props.delay ?? 900)
  settleTimer = setTimeout(showTooltip, delay)
}

const startHover = (e: MouseEvent) => {
  // Ignore touch events (no fine pointer and no confirmed real mouse)
  if (!hasFinePointer() && !hasRealMouse) return

  mouseX.value = e.clientX
  mouseY.value = e.clientY
  lastMoveX = e.clientX
  lastMoveY = e.clientY
}

const updatePosition = (e: MouseEvent) => {
  // Detect real mouse via movement (touch events don't generate continuous mousemove)
  if (e.movementX !== 0 || e.movementY !== 0) hasRealMouse = true
  if (!hasFinePointer() && !hasRealMouse) return

  mouseX.value = e.clientX
  mouseY.value = e.clientY

  // If tooltip is already visible, just update position
  if (visible.value) return

  const dx = e.clientX - lastMoveX
  const dy = e.clientY - lastMoveY
  const distance = Math.sqrt(dx * dx + dy * dy)

  // If cursor moved beyond threshold, reset settle timer
  if (distance > SETTLE_THRESHOLD) {
    lastMoveX = e.clientX
    lastMoveY = e.clientY
    if (settleTimer) {
      clearTimeout(settleTimer)
      settleTimer = null
    }
  }

  // Schedule tooltip when cursor settles
  if (!settleTimer) {
    scheduleTooltip()
  }
}

const endHover = () => {
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  visible.value = false
  // Deactivate global state after a short delay if no new tooltip started
  if (globalDeactivateTimer) clearTimeout(globalDeactivateTimer)
  globalDeactivateTimer = setTimeout(() => {
    globalActive = false
  }, 400)
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
