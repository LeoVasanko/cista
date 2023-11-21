<template>
  <template v-if="store.selected.size">
    <div class="smallgap"></div>
    <p class="select-text">{{ store.selected.size }} selected ➤</p>
    <DownloadButton />
    <SvgButton name="copy" data-tooltip="Copy here" @click="op('cp', dst)" />
    <SvgButton name="paste" data-tooltip="Move here" @click="op('mv', dst)" />
    <SvgButton name="trash" data-tooltip="Delete ⚠️" @click="op('rm')" />
    <button class="action-button unselect" data-tooltip="Unselect all" @click="store.selected.clear()">❌</button>
  </template>
</template>

<script setup lang="ts">
import {connect, controlUrl} from '@/repositories/WS'
import { useMainStore } from '@/stores/main'
import { computed } from 'vue'

const store = useMainStore()
const props = defineProps({
  path: Array<string>
})

const dst = computed(() => props.path!.join('/'))
const op = (op: string, dst?: string) => {
  const sel = store.selectedFiles
  const msg = {
    op,
    sel: sel.keys.map(key => {
      const doc = sel.docs[key]
      return doc.loc ? `${doc.loc}/${doc.name}` : doc.name
    })
  }
  // @ts-ignore
  if (dst !== undefined) msg.dst = dst
  const control = connect(controlUrl, {
    message(ev: MessageEvent) {
      const res = JSON.parse(ev.data)
      if ('error' in res) {
        console.error('Control socket error', msg, res.error)
        store.error = res.error.message
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
.select-text {
  color: var(--accent-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0;
}
</style>
