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
// Track recent touch to suppress touch-triggered mouse events
let lastTouchTime = 0
</script>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'

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

// Track touch events globally to suppress touch-simulated mouse events
const onTouchStart = () => { lastTouchTime = Date.now() }
onMounted(() => document.addEventListener('touchstart', onTouchStart, { passive: true }))
onUnmounted(() => document.removeEventListener('touchstart', onTouchStart))

// Check if event is likely from touch (touch happened within last 500ms)
const isTouchEvent = () => Date.now() - lastTouchTime < 500

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
  // Ignore touch-simulated mouse events
  if (isTouchEvent()) return

  mouseX.value = e.clientX
  mouseY.value = e.clientY
  lastMoveX = e.clientX
  lastMoveY = e.clientY
}

const updatePosition = (e: MouseEvent) => {
  // Ignore touch-simulated mouse events
  if (isTouchEvent()) return

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
  box-shadow: 0 0 1rem rgba(0, 0, 0, 0.5);
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  color: #fff;
  white-space: nowrap;
  pointer-events: none;
  font-size: 1rem;
}
</style>
