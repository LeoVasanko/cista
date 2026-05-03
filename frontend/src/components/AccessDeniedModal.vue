<template>
  <ModalDialog name="accessdenied" title="">
    <div class="access-denied">
      <p class="icon">⛔</p>
      <p class="message">Access Denied</p>
      <button @click="reload" class="button">Reload</button>
    </div>
  </ModalDialog>
</template>

<script setup lang="ts">
import ModalDialog from '@/components/ModalDialog.vue'

const reload = () => {
  location.reload()
}
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
