<template>
  <button
    class="action-button"
    @mouseenter="tooltip?.startHover"
    @mousemove="tooltip?.updatePosition"
    @mouseleave="tooltip?.endHover"
  >
    <component :is="icons[name]" />
    <slot></slot>
    <CursorTooltip v-if="tooltipText" ref="tooltip" :text="tooltipText">{{ tooltipText }}</CursorTooltip>
  </button>
</template>

<script setup lang="ts">
import { icons, type IconName } from '@/assets/svg'
import { ref } from 'vue'
import CursorTooltip from './CursorTooltip.vue'

const props = defineProps<{
  name: IconName
  tooltip?: string
}>()

const tooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)
const tooltipText = props.tooltip ?? ''
</script>

<style>
.action-button {
  background: none;
  border: none;
  color: #ccc;
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 0.2em;
  width: 3em;
  height: 3em;
}
.action-button:hover,
.action-button:focus {
  color: #fff;
  transform: scale(1.1);
}
svg {
  fill: #ccc;
  transform: fill 0.2s ease;
}
.action-button:hover svg,
.action-button:focus svg {
  fill: #fff;
}
</style>
