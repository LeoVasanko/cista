<template>
  <div v-if="!props.path || documents.length === 0" class="empty-container">
    <component :is="cog" :class="['cog', { stopped: store.dialog === 'accessdenied' || store.authInProgress }]"/>
    <p v-if="store.dialog === 'accessdenied'">Access Denied</p>
    <p v-else-if="!store.connected">No Connection</p>
    <p v-else-if="store.documentCount === 0">Waiting for File List</p>
    <p v-else-if="store.query">No matches!</p>
    <p v-else-if="!exists(props.path)">Folder not found</p>
    <p v-else>Empty folder</p>
  </div>
</template>

<script setup lang="ts">
import { Cog } from '@/assets/svg'
import { useMainStore } from '@/stores/main'
import { exists } from '@/utils/fileutil'

const cog = Cog
const store = useMainStore()
const props = defineProps<{
  path: string[]
  documents: Document[]
}>()
</script>

<style scoped>
@keyframes rotate {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
svg.cog {
  width: 10rem;
  height: 10rem;
  margin: 0 auto;
  animation: rotate 10s linear infinite;
  filter: drop-shadow(0 0 1rem black);
  fill: #888;
}
svg.cog.stopped {
  animation: none;
}
</style>
