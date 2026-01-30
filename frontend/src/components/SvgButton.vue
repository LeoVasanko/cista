<template>
  <button class="action-button">
    <component :is="icons[name]" />
    <slot></slot>
  </button>
</template>

<script setup lang="ts">
import { icons, type IconName } from '@/assets/svg'

defineProps<{
  name: IconName
}>()
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
