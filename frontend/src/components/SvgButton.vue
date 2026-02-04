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
  margin: 0 0.2em;
  padding: 0;
  width: 2.7em;
  height: 2.7em;
  min-width: 1.9em;
  min-height: 1.9em;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.action-button:hover,
.action-button:focus {
  color: #fff;
  transform: scale(1.1);
}
.action-button svg {
  fill: #ccc;
  transition: fill 0.2s ease;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: 100%;
}
.action-button:hover svg,
.action-button:focus svg {
  fill: #fff;
}
</style>
