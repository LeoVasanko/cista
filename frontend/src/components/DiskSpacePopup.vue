<template>
  <div class="disk-space-container" ref="containerRef">
    <div
      class="disk-space-widget"
      :class="{ expanded: isExpanded }"
      :style="widgetStyle"
    >
      <svg viewBox="0 0 150 150" class="pie-svg" preserveAspectRatio="xMidYMid meet">
      <defs>
        <filter id="pieShadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="rgba(0,0,0,0.4)" />
        </filter>
        <radialGradient id="storageGradient" cx="30%" cy="30%" r="70%">
          <stop offset="0%" stop-color="#93e" />
          <stop offset="100%" stop-color="#82d" />
        </radialGradient>
        <radialGradient id="otherGradient" cx="30%" cy="30%" r="70%">
          <stop offset="0%" stop-color="#d9f" />
          <stop offset="100%" stop-color="#c8e" />
        </radialGradient>
        <radialGradient id="highlightOverlay" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="rgba(255,255,255,0.15)" />
          <stop offset="60%" stop-color="rgba(255,255,255,0)" />
          <stop offset="100%" stop-color="rgba(0,0,0,0.08)" />
        </radialGradient>
      </defs>

      <g :filter="isExpanded ? 'url(#pieShadow)' : 'none'">
        <circle :r="pieRadius" :cx="pieCx" :cy="pieCy" fill="url(#otherGradient)" />
        <circle :r="pieRadius/2" :cx="pieCx" :cy="pieCy" fill="transparent" :stroke="freeColor" :stroke-width="pieRadius" :stroke-dasharray="pieFreeDash" :stroke-dashoffset="pieFreeOffsetVal" :transform="`rotate(-90 ${pieCx} ${pieCy})`" />
        <circle :r="pieRadius/2" :cx="pieCx" :cy="pieCy" fill="transparent" stroke="url(#storageGradient)" :stroke-width="pieRadius" :stroke-dasharray="pieStorageDash" :transform="`rotate(-90 ${pieCx} ${pieCy})`" />
        <circle :r="pieRadius" :cx="pieCx" :cy="pieCy" fill="url(#highlightOverlay)" />
        <circle :r="pieRadius * 0.22" :cx="pieCx" :cy="pieCy" fill="#000" />
        <text :x="pieCx" :y="pieCy" dy="0.35em" class="pie-center-label" text-anchor="middle" :style="{ opacity: labelsOpacity }">GB</text>
        <circle :r="pieRadius" :cx="pieCx" :cy="pieCy" fill="transparent" class="pie-hitarea" @click="handleClick" />
      </g>

      <g class="pie-labels" :style="{ opacity: labelsOpacity }">
        <text :x="storageInnerPos.x" :y="storageInnerPos.y" class="pie-label-inner" :text-anchor="getSizeAnchor(sectorInfo.storage.angle)" dominant-baseline="middle" :transform="`rotate(${getSizeRotation(sectorInfo.storage.angle)} ${storageInnerPos.x} ${storageInnerPos.y})`">{{ fmtSize(store.space.storage, sectorInfo.storage.angle) }}</text>
        <text :x="freeInnerPos.x" :y="freeInnerPos.y" class="pie-label-inner" :text-anchor="getSizeAnchor(sectorInfo.free.angle)" dominant-baseline="middle" :transform="`rotate(${getSizeRotation(sectorInfo.free.angle)} ${freeInnerPos.x} ${freeInnerPos.y})`">{{ fmtSize(store.space.free, sectorInfo.free.angle) }}</text>
        <text :x="otherInnerPos.x" :y="otherInnerPos.y" class="pie-label-inner" :text-anchor="getSizeAnchor(sectorInfo.other.angle)" dominant-baseline="middle" :transform="`rotate(${getSizeRotation(sectorInfo.other.angle)} ${otherInnerPos.x} ${otherInnerPos.y})`">{{ fmtSize(store.space.usage - store.space.storage, sectorInfo.other.angle) }}</text>

        <defs>
          <path :id="storageLabelPath.id" :d="storageLabelPath.d" fill="none" />
          <path :id="freeLabelPath.id" :d="freeLabelPath.d" fill="none" />
          <path :id="otherLabelPath.id" :d="otherLabelPath.d" fill="none" />
        </defs>

        <text class="pie-label-sub">
          <textPath :href="'#' + storageLabelPath.id" startOffset="50%" text-anchor="middle" dominant-baseline="middle">{{ storageName }}</textPath>
        </text>
        <text class="pie-label-sub">
          <textPath :href="'#' + freeLabelPath.id" startOffset="50%" text-anchor="middle" dominant-baseline="middle">free</textPath>
        </text>
        <text class="pie-label-sub">
          <textPath :href="'#' + otherLabelPath.id" startOffset="50%" text-anchor="middle" dominant-baseline="middle">other</textPath>
        </text>
      </g>
    </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMainStore } from '@/stores/main'

const store = useMainStore()
const containerRef = ref<HTMLDivElement | null>(null)

const isExpanded = ref(false)
const animProgress = ref(0)
const labelsOpacity = ref(0)
let animationFrame: number | null = null

const BASE_SIZE = 48
const EXPANDED_SCALE = 320 / 48
const containerPos = ref({ top: 0, left: 0 })

const formatGB = (bytes: number) => {
  const gb = bytes / (1024 * 1024 * 1024)
  return gb < 10 ? gb.toFixed(1) : `${Math.round(gb)}`
}

// Add dot suffix for ambiguous angles (within 15° of horizontal) on numbers that look same upside down
const fmtSize = (bytes: number, angle: number) => {
  const s = formatGB(bytes)
  const a = Math.abs(angle % 180)
  return (Math.min(a, 180 - a) < 15 && /^[0689]+$/.test(s)) ? `${s}.` : s
}

const truncateLabel = (name: string, maxLen = 10): string => {
  if (name.length <= maxLen) return name
  const parts = name.split(/[\s\-_.,;:!?()\[\]{}]+/)
  if (parts[0] && parts[0].length <= maxLen) return parts[0]
  return name.slice(0, maxLen - 1) + '…'
}

const storageName = computed(() => truncateLabel(store.server.name || 'stored'))

const pieCx = 75
const pieCy = 75
const pieRadius = 55
const CIRC = Math.PI * pieRadius

const pieStorageDash = computed(() => {
  const s = store.space
  if (!s.disk) return `0 ${CIRC}`
  return `${(s.storage / s.disk) * CIRC} ${CIRC}`
})

const pieFreeDash = computed(() => {
  const s = store.space
  if (!s.disk) return `0 ${CIRC}`
  return `${(s.free / s.disk) * CIRC} ${CIRC}`
})

const pieFreeOffsetVal = computed(() => {
  const s = store.space
  if (!s.disk) return 0
  return -(s.storage / s.disk) * CIRC
})

const freeColor = computed(() => {
  const s = store.space
  if (!s.disk) return '#6c6'
  const freePct = s.free / s.disk
  if (freePct > 0.25) return '#5b5'
  if (freePct > 0.10) return '#db3'
  return '#d44'
})

const PIE_RADIUS = 55
const LABEL_RADIUS = 62

const getPoint = (angle: number, radius: number) => {
  const rad = (angle - 90) * Math.PI / 180
  return { x: pieCx + radius * Math.cos(rad), y: pieCy + radius * Math.sin(rad) }
}

const sectorInfo = computed(() => {
  const s = store.space
  if (!s.disk) return {
    storage: { angle: 45, pct: 0.25 },
    free: { angle: 180, pct: 0.5 },
    other: { angle: 270, pct: 0.25 }
  }

  const storagePct = s.storage / s.disk
  const freePct = s.free / s.disk
  const otherPct = (s.usage - s.storage) / s.disk

  const storageAngle = storagePct * 180  // midpoint of storage sector
  const freeStart = storagePct * 360
  const freeAngle = freeStart + freePct * 180
  const otherStart = (storagePct + freePct) * 360
  const otherAngle = otherStart + otherPct * 180

  return {
    storage: { angle: storageAngle, pct: storagePct },
    free: { angle: freeAngle, pct: freePct },
    other: { angle: otherAngle, pct: otherPct }
  }
})

const rawAngles = computed(() => ({
  storage: sectorInfo.value.storage.angle,
  free: sectorInfo.value.free.angle,
  other: sectorInfo.value.other.angle
}))

const getSizeRotation = (angle: number) => angle < 180 ? angle - 90 : angle + 90
const getSizeAnchor = (angle: number) => angle < 180 ? 'end' : 'start'

const INNER_LABEL_RADIUS = PIE_RADIUS * 0.95
const storageInnerPos = computed(() => getPoint(sectorInfo.value.storage.angle, INNER_LABEL_RADIUS))
const freeInnerPos = computed(() => getPoint(sectorInfo.value.free.angle, INNER_LABEL_RADIUS))
const otherInnerPos = computed(() => getPoint(sectorInfo.value.other.angle, INNER_LABEL_RADIUS))

// Collision avoidance for curved name labels
const labelLengths = computed(() => ({
  storage: storageName.value.length,
  free: 4,
  other: 5
}))

const getGapForPair = (len1: number, len2: number) => {
  return 35 + Math.max(0, len1 + len2 - 8) * 2.5
}

const adjustedLabelAngles = computed(() => {
  const angles = rawAngles.value
  const lens = labelLengths.value
  const labels = [
    { id: 'storage', angle: angles.storage, len: lens.storage },
    { id: 'free', angle: angles.free, len: lens.free },
    { id: 'other', angle: angles.other, len: lens.other }
  ]
  labels.sort((a, b) => a.angle - b.angle)

  for (let iterations = 0; iterations < 15; iterations++) {
    let moved = false
    for (let i = 0; i < labels.length; i++) {
      const current = labels[i]!
      const next = labels[(i + 1) % labels.length]!
      let angleDiff = next.angle - current.angle
      if (angleDiff < 0) angleDiff += 360
      const requiredGap = getGapForPair(current.len, next.len)
      if (angleDiff < requiredGap) {
        const push = (requiredGap - angleDiff) / 2
        current.angle = (current.angle - push + 360) % 360
        next.angle = (next.angle + push) % 360
        moved = true
      }
    }
    if (!moved) break
  }

  const result: Record<string, number> = {}
  for (const l of labels) result[l.id] = l.angle
  return result
})

// Arc path for curved text labels (CW for top half, CCW for bottom half)
const createArcPath = (centerAngle: number, id: string) => {
  const radius = LABEL_RADIUS
  const arcSpan = 60
  const isBottom = centerAngle > 90 && centerAngle <= 270
  const startAngle = isBottom ? centerAngle + arcSpan / 2 : centerAngle - arcSpan / 2
  const endAngle = isBottom ? centerAngle - arcSpan / 2 : centerAngle + arcSpan / 2
  const start = getPoint(startAngle, radius)
  const end = getPoint(endAngle, radius)
  const sweep = isBottom ? 0 : 1
  return {
    id: `label-path-${id}`,
    d: `M ${start.x} ${start.y} A ${radius} ${radius} 0 0 ${sweep} ${end.x} ${end.y}`
  }
}

const storageLabelPath = computed(() => createArcPath(adjustedLabelAngles.value.storage!, 'storage'))
const freeLabelPath = computed(() => createArcPath(adjustedLabelAngles.value.free!, 'free'))
const otherLabelPath = computed(() => createArcPath(adjustedLabelAngles.value.other!, 'other'))

const widgetStyle = computed(() => {
  const t = animProgress.value
  const eased = 1 - Math.pow(1 - t, 3)
  const scale = 1 + (EXPANDED_SCALE - 1) * eased
  const expandedTranslateX = window.innerWidth - containerPos.value.left - BASE_SIZE
  const expandedTranslateY = -containerPos.value.top
  const translateX = expandedTranslateX * eased
  const translateY = expandedTranslateY * eased
  return {
    transform: `translate(${translateX}px, ${translateY}px) scale(${scale})`,
    transformOrigin: 'top right',
    zIndex: isExpanded.value ? 1001 : 'auto',
  }
})

const handleClick = () => isExpanded.value ? collapse() : expand()

const animate = (startTime: number, duration: number, from: number, to: number, onComplete?: () => void) => {
  const tick = (now: number) => {
    const elapsed = now - startTime
    const progress = Math.min(elapsed / duration, 1)
    animProgress.value = from + (to - from) * progress
    labelsOpacity.value = to > from ? progress : 1 - progress
    if (progress < 1) {
      animationFrame = requestAnimationFrame(tick)
    } else {
      animationFrame = null
      onComplete?.()
    }
  }
  animationFrame = requestAnimationFrame(tick)
}

const expand = () => {
  if (animationFrame) cancelAnimationFrame(animationFrame)
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    containerPos.value = { top: rect.top, left: rect.left }
  }
  isExpanded.value = true
  animate(performance.now(), 300, 0, 1)
}

const collapse = () => {
  if (animationFrame) cancelAnimationFrame(animationFrame)
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    containerPos.value = { top: rect.top, left: rect.left }
  }
  animate(performance.now(), 300, 1, 0, () => {
    isExpanded.value = false
  })
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && isExpanded.value) collapse()
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  if (animationFrame) cancelAnimationFrame(animationFrame)
})
</script>

<style scoped>
.disk-space-container {
  position: relative;
  width: 3em;
  height: 3em;
}

.disk-space-widget {
  position: absolute;
  top: 0;
  left: 0;
  width: 3em;
  height: 3em;
  cursor: pointer;
  will-change: transform;
}

.disk-space-widget.expanded {
  pointer-events: none;
}

.pie-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
}

.pie-hitarea {
  pointer-events: auto;
  cursor: pointer;
}

.pie-label-inner {
  fill: #fff;
  font-size: 12px;
  font-weight: 700;
  stroke: #000;
  stroke-width: 0.5px;
  paint-order: stroke fill;
}

.pie-center-label {
  fill: #fff;
  font-size: 10px;
  font-weight: 600;
}

.pie-label-sub {
  fill: #fff;
  font-size: 14px;
  font-weight: 600;
  font-variant: small-caps;
  text-transform: lowercase;
  stroke: #000;
  stroke-width: 1px;
  paint-order: stroke fill;
}
</style>
