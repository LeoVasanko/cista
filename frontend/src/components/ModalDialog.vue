<template>
  <div v-if="store.dialog === name" class="modal-overlay" @click.self="close" @keydown.escape="close" tabindex="-1" ref="overlay">
    <div class="modal-dialog" :id="props.name" ref="dialog">
      <h1 v-if="props.title">{{ props.title }}</h1>
      <div class="modal-content">
        <slot>
          Dialog with no content
          <button @click="close">OK</button>
        </slot>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import { holdGlobalBackdrop, releaseGlobalBackdrop } from 'paskia'
import { nextTick, ref, watchEffect } from 'vue'

const overlay = ref<HTMLDivElement | null>(null)
const dialog = ref<HTMLDivElement | null>(null)
const store = useMainStore()

const close = () => {
  store.dialog = ''
  releaseGlobalBackdrop()
}

const props = defineProps<{
  title: string
  name: typeof store.dialog
}>()

const show = () => {
  store.dialog = props.name
  holdGlobalBackdrop()
  nextTick(() => {
    overlay.value?.focus()
    const input = dialog.value?.querySelector('input')
    if (input) input.focus()
  })
}
defineExpose({ show, close })
watchEffect(() => {
  if (overlay.value) {
    overlay.value.focus()
    const input = dialog.value?.querySelector('input')
    if (input) input.focus()
  }
})
</script>

<style>
/* ===========================================
   MODAL DIALOG GLOBAL STYLES
   Shared styling for all modal dialogs.
   Login page (auth.py) has matching CSS.
   =========================================== */

/* Overlay - covers entire viewport */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  /* No backdrop - paskia handles that */
}

/* Dialog container */
.modal-dialog {
  background: #ddd;
  color: #000;
  border: none;
  border-radius: 0.5rem;
  box-shadow: 0 0 1rem #0008;
  padding: 0;
  max-width: 90vw;
  max-height: 90vh;
  overflow: auto;
  font-size: 1rem;
}

/* Dialog title bar */
.modal-dialog > h1 {
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
.modal-dialog > .modal-content {
  padding: 1rem;
}

/* Section headings inside dialog */
.modal-dialog h3 {
  font-size: 1rem;
  font-weight: 600;
  margin: 1rem 0 0.5rem 0;
}
.modal-dialog h3:first-child {
  margin-top: 0;
}

/* Links */
.modal-dialog a {
  color: #146;
}
.modal-dialog a:hover {
  color: #f80;
}

/* Form inputs */
.modal-dialog input[type="text"],
.modal-dialog input[type="password"],
.modal-dialog select {
  font: inherit;
  font-size: 1rem;
  padding: 0.5rem;
  border: 2px solid #888;
  border-radius: 0.25rem;
  background: #fff;
  color: #000;
  min-width: 12rem;
}

.modal-dialog input[type="text"]:focus,
.modal-dialog input[type="password"]:focus,
.modal-dialog select:focus {
  outline: none;
  border-color: #f80;
}

/* Labels */
.modal-dialog label {
  font-size: 1rem;
}

/* Buttons */
.modal-dialog button,
.modal-dialog input[type="submit"],
.modal-dialog input[type="reset"],
.modal-dialog .button {
  font: inherit;
  font-size: 1rem;
  padding: 0.5rem 1rem;
  background: #146;
  color: #fff;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
}

.modal-dialog button:hover,
.modal-dialog input[type="submit"]:hover,
.modal-dialog input[type="reset"]:hover,
.modal-dialog .button:hover {
  background: #f80;
}

.modal-dialog button:disabled,
.modal-dialog input[type="submit"]:disabled,
.modal-dialog input[type="reset"]:disabled,
.modal-dialog .button:disabled {
  background: #888;
  cursor: not-allowed;
}

/* Small button variant */
.modal-dialog .button.small {
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
}

/* Danger button variant */
.modal-dialog .button.danger {
  background: #c00;
}
.modal-dialog .button.danger:hover:not(:disabled) {
  background: #f00;
}

/* Form row layout (label + input side by side) */
.modal-dialog .form-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  align-items: center;
  margin-bottom: 0.5rem;
}

/* Form grid for multiple label+input pairs */
.modal-dialog .form-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  align-items: center;
}

/* Dialog button row (footer) */
.modal-dialog .dialog-buttons {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
}

/* Error text */
.modal-dialog .error-text {
  color: #c00;
  font-size: 0.875rem;
  min-height: 1.2em;
  margin: 0.5rem 0;
}

/* Success message */
.modal-dialog .success-message {
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
.modal-dialog table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.5rem 0;
  font-size: 1rem;
}

.modal-dialog th,
.modal-dialog td {
  border: 1px solid #888;
  padding: 0.5rem;
  text-align: left;
}

.modal-dialog th {
  background: #146;
  color: #fff;
  font-weight: normal;
}

.modal-dialog td {
  background: #fff;
}

/* Checkbox alignment in tables */
.modal-dialog td input[type="checkbox"] {
  margin: 0;
}

/* Paragraph text */
.modal-dialog p {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
}

/* Loading state */
.modal-dialog .loading {
  padding: 2rem;
  text-align: center;
  color: #666;
}
</style>
