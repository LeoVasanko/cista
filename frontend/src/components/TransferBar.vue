<template>
  <div class="transferprogress" v-if="status.total" :style="`background: linear-gradient(to right, var(--bar) 0, var(--bar) ${percent}%, var(--nobar) ${percent}%, var(--nobar) 100%);`">
    <div class="statustext">
      <span v-if="status.filecount > 1" class="index">
        [{{ status.fileidx }}/{{ status.filecount }}]
      </span>
      <span class="filename">{{ status.filename.split('/').pop() }}
        <span v-if="status.filesize > 1e7" class="percent">
          {{ (status.filepos / status.filesize * 100).toFixed(0) + '\u202F%' }}
        </span>
      </span>
      <span class="position" v-if="status.total > 1e7">
        {{ (status.xfer / 1e6).toFixed(0) + '\u202F/\u202F' + (status.total / 1e6).toFixed(0) + '\u202FMB' }}
      </span>
      <span class="speed">{{ speeddisp }}</span>
      <button class="close" @click="$emit('cancel')">❌</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

defineEmits(['cancel'])

const props = defineProps<{
  status: {
    total: number
    xfer: number
    filecount: number
    fileidx: number
    filesize: number
    filepos: number
    filename: string
    statbytes: number
    statdur: number
    tlast: number
  }
}>()

const percent = computed(() => props.status.xfer / props.status.total * 100)
const speed = computed(() => {
  let s = props.status.statbytes / props.status.statdur / 1e3
  const tsince = (Date.now() - props.status.tlast) / 1e3
  if (tsince > 5 / s) return 0  // Less than fifth of previous speed => stalled
  if (tsince > 1 / s) return 1 / tsince  // Next block is late or not coming, decay
  return s  // "Current speed"
})
const speeddisp = computed(() => speed.value ? speed.value.toFixed(speed.value < 10 ? 1 : 0) + '\u202FMB/s': 'stalled')

</script>

<style scoped>
.transferprogress {
  --bar: var(--accent-color);
  --nobar: transparent;
  display: flex;
  flex-direction: column;
  justify-content: center;
  color: var(--primary-color);
  width: 100%;
}
.statustext {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 .5em;
  padding: 0.5rem 0;
}
span {
  color: #ccc;
  white-space: nowrap;
  text-align: right;
  padding: 0 0.5em;
}
.filename {
  color: #fff;
  flex: 1 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}
.index { min-width: 3.5em }
.position { min-width: 4em }
.speed { min-width: 4em }

.upload .statustext::before {
  font-size: 1.5em;
  content: '🔺'
}
.download .statustext::before {
  font-size: 1.5em;
  content: '🔻'
}
</style>
