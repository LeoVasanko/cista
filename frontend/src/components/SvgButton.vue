<template>
  <button class="action-button">
    <component :is="icon" />
    <slot></slot>
  </button>
</template>

<script setup lang="ts">
import { defineAsyncComponent } from 'vue'

const props = defineProps<{
  name: string
}>()

const icon = defineAsyncComponent(() => import(`@/assets/svg/${props.name}.svg`))
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
