<template>
  <div v-if="store.dialog === 'accessdenied'" class="modal-overlay">
    <div class="modal-dialog" id="accessdenied">
      <div class="modal-content access-denied">
        <p class="icon">⛔</p>
        <p class="message">Access Denied</p>
        <button @click="reload" class="button">Reload</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import { holdGlobalBackdrop } from 'paskia'
import { watchEffect } from 'vue'

const store = useMainStore()

const reload = () => {
  location.reload()
}

// Keep backdrop active when this dialog shows
watchEffect(() => {
  if (store.dialog === 'accessdenied') {
    holdGlobalBackdrop()
  }
})
</script>

<style scoped>
.access-denied {
  text-align: center;
  padding: 2rem !important;
}
.access-denied .icon {
  font-size: 4rem;
  margin: 0 0 1rem 0;
}
.access-denied .message {
  font-size: 1.5rem;
  font-weight: bold;
  margin: 0 0 1.5rem 0;
}
</style>
