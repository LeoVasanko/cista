<template>
  <Teleport to="body">
    <div v-if="visible" ref="tooltipEl" class="cursor-tooltip" :style="tooltipStyle">
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
const tooltipWidth = ref(0)
const tooltipHeight = ref(0)
const tooltipEl = ref<HTMLElement | null>(null)
let settleTimer: ReturnType<typeof setTimeout> | null = null
let lastMoveX = 0
let lastMoveY = 0

// Movement threshold (pixels) - cursor must settle within this radius
const SETTLE_THRESHOLD = 8

const tooltipStyle = computed(() => {
  // Constrain to viewport
  const pad = 8
  let x = mouseX.value
  let y = mouseY.value

  // Only constrain if we've measured the tooltip
  if (tooltipWidth.value > 0 && tooltipHeight.value > 0) {
    // Adjust horizontal position if tooltip would overflow right edge
    if (x + tooltipWidth.value + pad > window.innerWidth) {
      x = window.innerWidth - tooltipWidth.value - pad
    }
    // Adjust vertical position if tooltip would overflow bottom edge
    if (y + tooltipHeight.value + pad > window.innerHeight) {
      y = window.innerHeight - tooltipHeight.value - pad
    }
    // Don't go past left/top edges
    x = Math.max(pad, x)
    y = Math.max(pad, y)
  }

  return {
    left: `${x}px`,
    top: `${y}px`,
  }
})

// Track touch events globally to suppress touch-simulated mouse events
const onTouchStart = () => { lastTouchTime = Date.now() }
onMounted(() => document.addEventListener('touchstart', onTouchStart, { passive: true }))
onUnmounted(() => document.removeEventListener('touchstart', onTouchStart))

// Check if event is likely from touch (touch happened within last 500ms)
const isTouchEvent = () => Date.now() - lastTouchTime < 500

const showTooltip = () => {
  visible.value = true
  globalActive = true
  // Measure tooltip after it renders
  requestAnimationFrame(() => {
    if (tooltipEl.value) {
      tooltipWidth.value = tooltipEl.value.offsetWidth
      tooltipHeight.value = tooltipEl.value.offsetHeight
    }
  })
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
  pointer-events: none;
  font-size: 1rem;
}
</style>
