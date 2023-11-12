<template>
  <dialog ref="dialog">
    <h1 v-if="props.title">{{ props.title }}</h1>
    <div>
      <slot>
        Dialog with no content
        <button onclick="dialog.close()">OK</button>
      </slot>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const dialog = ref<HTMLDialogElement | null>(null)

const props = withDefaults(
  defineProps<{
    title: string
  }>(),
  {
    title: ''
  }
)
const show = () => {
  dialog.value!.showModal()
}
defineExpose({ show })
onMounted(() => {
  show()
})
</script>

<style>
/* Style for the background */
dialog::backdrop {
  content: '';
  display: block;
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: #0008;
  backdrop-filter: blur(0.4em);
  z-index: 1000;
}

/* Hide the dialog by default */
dialog[open] {
  background: #ddd;
  color: black;
  display: block;
  border: none;
  font-size: 1.2rem;
  border-radius: 0.5rem;
  box-shadow: 0.2rem 0.2rem 1rem #000;
  padding: 1rem;
  position: fixed;
  top: 0;
  left: 0;
  z-index: 1001;
}
input {
  font: inherit;
}
dialog[open] > h1 {
  background: var(--soft-color);
  color: #fff;
  font-size: 1.2rem;
  margin: -1rem -1rem 0 -1rem;
  padding: 0.5rem 1rem 0.5rem 1rem;
}

dialog[open] > div {
  padding: 1em 0;
}
</style>
