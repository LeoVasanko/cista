<template>
  <div v-if="showEmpty" class="empty-container">
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
import { computed } from 'vue'

const cog = Cog
const store = useMainStore()
const props = defineProps<{
  path: string[]
  documents: Document[]
}>()

const showEmpty = computed(() => {
  const loc = props.path.join('/')
  const hasVisibleGhost = store.ghosts.some(g => {
    const full = g.loc ? `${g.loc}/${g.name}` : g.name
    return g.loc === loc && !store.hiddenPaths.has(full)
  })

  return !props.path || (props.documents.length === 0 && !hasVisibleGhost)
})
</script>

<style scoped>
.empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 2rem;
  text-shadow: 0 0 .3rem #000, 0 0 2rem #0008;
  color: var(--accent-color);
}
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
