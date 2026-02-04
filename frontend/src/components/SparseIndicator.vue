<template>
  <span v-if="doc.sparseIndicator" class="sparse-indicator">{{ doc.sparseIndicator }}</span>
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'

defineProps<{
  doc: Doc
}>()
</script>

<style scoped>
.sparse-indicator {
  opacity: 0.7;
}
</style>
