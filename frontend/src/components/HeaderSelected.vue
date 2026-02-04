<template>
  <div class="selection-bar" v-if="store.selected.size">
    <p class="select-text">{{ store.selected.size }} selected</p>
    <DownloadButton />
    <SvgButton name="copy" tooltip="Copy here" @click="op('cp', dst)" />
    <SvgButton name="paste" tooltip="Move here" @click="op('mv', dst)" />
    <SvgButton name="trash" tooltip="Delete ⚠️" @click="op('rm')" />
    <button
      class="action-button unselect"
      @click="store.selected.clear()"
      @mouseenter="unselectTooltip?.startHover"
      @mousemove="unselectTooltip?.updatePosition"
      @mouseleave="unselectTooltip?.endHover"
    >❌<CursorTooltip ref="unselectTooltip" text="Unselect all">Unselect all</CursorTooltip></button>
  </div>
</template>

<script setup lang="ts">
import {connect, controlUrl} from '@/repositories/WS'
import { useMainStore } from '@/stores/main'
import { computed, ref } from 'vue'
import CursorTooltip from './CursorTooltip.vue'

const unselectTooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)

const store = useMainStore()
const props = defineProps({
  path: Array<string>
})

const dst = computed(() => props.path!.join('/'))
const op = (opName: string, dst?: string) => {
  const sel = store.selectedFiles
  const paths = sel.keys.map(key => {
    const doc = sel.docs[key]!
    return doc.loc ? `${doc.loc}/${doc.name}` : doc.name
  })
  const msg = {
    op: opName,
    sel: paths
  }
  // @ts-ignore
  if (dst !== undefined) msg.dst = dst
  // Hide items being deleted or moved (optimistic update)
  if (opName === 'rm' || opName === 'mv') {
    for (const path of paths) store.hideDoc(path)
  }
  const control = connect(controlUrl, {
    message(ev: MessageEvent) {
      const res = JSON.parse(ev.data)
      if ('error' in res) {
        console.error('Control socket error', msg, res.error)
        store.error = res.error.message
        // Restore hidden items on error
        if (opName === 'rm' || opName === 'mv') {
          for (const path of paths) store.unhideDoc(path)
        }
        return
      } else if (res.status === 'ack') {
        console.log('Control ack OK', res)
        control.close()
        store.selected.clear()
        return
      } else console.log('Unknown control response', msg, res)
    }
  })
  control.onopen = () => {
    control.send(JSON.stringify(msg))
  }
}

</script>

<style>
.selection-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.3em 0.5em;
  background: transparent;
  color: var(--header-color);
}
.select-text {
  color: var(--accent-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0;
  padding-right: 0.5em;
}
</style>
