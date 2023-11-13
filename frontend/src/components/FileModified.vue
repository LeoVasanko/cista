<template>
  <td class="modified right">
    <time :data-tooltip=tooltip :datetime=datetime>{{ doc.modified }}</time>
  </td>
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { computed } from 'vue'

const datetime = computed(() =>
  new Date(1000 * props.doc.mtime).toISOString().replace('.000Z', 'Z')
)

const tooltip = computed(() =>
  datetime.value.replace('T', '\n').replace('Z', ' UTC')
)

const props = defineProps<{
    doc: Doc
}>()
</script>
