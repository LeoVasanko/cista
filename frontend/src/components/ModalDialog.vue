<template>
  <dialog v-if="store.dialog === name" ref="dialog" :id=props.name @keydown.escape=close>
    <h1 v-if="props.title">{{ props.title }}</h1>
    <div>
      <slot>
        Dialog with no content
        <button @click=close>OK</button>
      </slot>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, onMounted, watchEffect, nextTick } from 'vue'
import { useMainStore } from '@/stores/main'
import { holdGlobalBackdrop, releaseGlobalBackdrop } from 'paskia'

const dialog = ref<HTMLDialogElement | null>(null)
const store = useMainStore()

const close = () => {
  dialog.value!.close()
  store.dialog = ''
  releaseGlobalBackdrop()
}

const props = defineProps<{
    title: string,
    name: typeof store.dialog,
  }>()

const show = () => {
  store.dialog = props.name
  holdGlobalBackdrop()
  setTimeout(() => {
    dialog.value!.showModal()
    nextTick(() => {
      const input = dialog.value!.querySelector('input')
      if (input) input.focus()
    })
  }, 0)
}
defineExpose({ show, close })
watchEffect(() => {
  if (dialog.value) show()
})
</script>

<style>
/* ===========================================
   DIALOG GLOBAL STYLES
   Shared styling for all modal dialogs.
   Login page (auth.py) has matching CSS.
   =========================================== */

dialog::backdrop {
  display: none;
}

/* Dialog container */
dialog[open] {
  background: #ddd;
  color: #000;
  border: none;
  border-radius: 0.5rem;
  box-shadow: 0 0 1rem #0008;
  padding: 0;
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 1100;
  max-width: 90vw;
  max-height: 90vh;
  overflow: auto;
  font-size: 1rem;
}

/* Dialog title bar */
dialog[open] > h1 {
  background: #146;
  color: #fff;
  font-size: 1.2rem;
  font-weight: normal;
  margin: 0;
  padding: 0.5rem 1rem;
  position: sticky;
  top: 0;
}

/* Dialog content area */
dialog[open] > div {
  padding: 1rem;
}

/* Section headings inside dialog */
dialog h3 {
  font-size: 1rem;
  font-weight: 600;
  margin: 1rem 0 0.5rem 0;
}
dialog h3:first-child {
  margin-top: 0;
}

/* Form inputs */
dialog input[type="text"],
dialog input[type="password"],
dialog select {
  font: inherit;
  font-size: 1rem;
  padding: 0.5rem;
  border: 2px solid #888;
  border-radius: 0.25rem;
  background: #fff;
  color: #000;
  min-width: 12rem;
}

dialog input[type="text"]:focus,
dialog input[type="password"]:focus,
dialog select:focus {
  outline: none;
  border-color: #f80;
}

/* Labels */
dialog label {
  font-size: 1rem;
}

/* Buttons */
dialog button,
dialog input[type="submit"],
dialog input[type="reset"],
dialog .button {
  font: inherit;
  font-size: 1rem;
  padding: 0.5rem 1rem;
  background: #146;
  color: #fff;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
}

dialog button:hover,
dialog input[type="submit"]:hover,
dialog input[type="reset"]:hover,
dialog .button:hover {
  background: #f80;
}

dialog button:disabled,
dialog input[type="submit"]:disabled,
dialog input[type="reset"]:disabled,
dialog .button:disabled {
  background: #888;
  cursor: not-allowed;
}

/* Small button variant */
dialog .button.small {
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
}

/* Danger button variant */
dialog .button.danger {
  background: #c00;
}
dialog .button.danger:hover:not(:disabled) {
  background: #f00;
}

/* Form row layout (label + input side by side) */
dialog .form-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  align-items: center;
  margin-bottom: 0.5rem;
}

/* Form grid for multiple label+input pairs */
dialog .form-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  align-items: center;
}

/* Dialog button row (footer) */
dialog .dialog-buttons {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
}

/* Error text */
dialog .error-text {
  color: #c00;
  font-size: 0.875rem;
  min-height: 1.2em;
  margin: 0.5rem 0;
}

/* Success message */
dialog .success-message {
  background: #f80;
  color: #000;
  padding: 0.5rem;
  border-radius: 0.25rem;
  margin: 0.5rem 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

/* Data tables inside dialogs */
dialog table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.5rem 0;
  font-size: 1rem;
}

dialog th,
dialog td {
  border: 1px solid #888;
  padding: 0.5rem;
  text-align: left;
}

dialog th {
  background: #146;
  color: #fff;
  font-weight: normal;
}

dialog td {
  background: #fff;
}

/* Checkbox alignment in tables */
dialog td input[type="checkbox"] {
  margin: 0;
}

/* Paragraph text */
dialog p {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
}

/* Loading state */
dialog .loading {
  padding: 2rem;
  text-align: center;
  color: #666;
}
</style>
