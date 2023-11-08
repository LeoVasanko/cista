<script setup lang="ts">
import { connect, uploadUrl } from '@/repositories/WS';
import { useDocumentStore } from '@/stores/documents'
import { collator } from '@/utils';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

const fileInput = ref()
const folderInput = ref()
const documentStore = useDocumentStore()
const props = defineProps({
  path: Array<string>
})


function uploadHandler(event: Event) {
  event.preventDefault()
  event.stopPropagation()
  // @ts-ignore
  let infiles = Array.from(event.dataTransfer?.files || event.target.files) as File[]
  if (!infiles.length) return
  const loc = props.path!.join('/')
  for (const f of infiles) {
    f.cloudName = loc + '/' + (f.webkitRelativePath || f.name)
    f.cloudPos = 0
  }
  const dotfiles = infiles.filter(f => f.cloudName.includes('/.'))
  if (dotfiles.length) {
    documentStore.error = "Won't upload dotfiles"
    console.log("Dotfiles omitted", dotfiles)
    infiles = infiles.filter(f => !f.cloudName.includes('/.'))
  }
  if (!infiles.length) return
  infiles.sort((a, b) => collator.compare(a.cloudName, b.cloudName))
  // @ts-ignore
  upqueue = upqueue.concat(infiles)
  statsAdd(infiles)
  startWorker()
}

const cancelUploads = () => {
  upqueue = []
  statReset()
}

const uprogress_init = {
  total: 0,
  uploaded: 0,
  t0: 0,
  tlast: 0,
  statbytes: 0,
  statdur: 0,
  files: [],
  filestart: 0,
  fileidx: 0,
  filecount: 0,
  filename: '',
  filesize: 0,
  filepos: 0,
}
const uprogress = reactive({...uprogress_init})
const percent = computed(() => uprogress.uploaded / uprogress.total * 100)
const speed = computed(() => {
  let s = uprogress.statbytes / uprogress.statdur / 1e3
  const tsince = (Date.now() - uprogress.tlast) / 1e3
  if (tsince > 5 / s) return 0  // Less than fifth of previous speed => stalled
  if (tsince > 1 / s) return 1 / tsince  // Next block is late or not coming, decay
  return s  // "Current speed"
})
const speeddisp = computed(() => speed.value ? speed.value.toFixed(speed.value < 100 ? 1 : 0) + '\u202FMB/s': 'stalled')
setInterval(() => {
  if (Date.now() - uprogress.tlast > 3000) {
    // Reset
    uprogress.statbytes = 0
    uprogress.statdur = 1
  } else {
    // Running average by decay
    uprogress.statbytes *= .9
    uprogress.statdur *= .9
  }
}, 100)
const statUpdate = ({name, size, start, end}) => {
  if (name !== uprogress.filename) return  // If stats have been reset
  const now = Date.now()
  uprogress.uploaded = uprogress.filestart + end
  uprogress.filepos = end
  uprogress.statbytes += end - start
  uprogress.statdur += now - uprogress.tlast
  uprogress.tlast = now
  // File finished?
  if (end === size) {
    uprogress.filestart += size
    statNextFile()
    if (++uprogress.fileidx >= uprogress.filecount) statReset()
  }
}
const statNextFile = () => {
  const f = uprogress.files.shift()
  if (!f) return statReset()
  uprogress.filepos = 0
  uprogress.filesize = f.size
  uprogress.filename = f.cloudName
}
const statReset = () => {
  Object.assign(uprogress, uprogress_init)
  uprogress.t0 = Date.now()
  uprogress.tlast = uprogress.t0 + 1
}
const statsAdd = (f: Array<File>) => {
  if (uprogress.files.length === 0) statReset()
  uprogress.total += f.reduce((a, b) => a + b.size, 0)
  uprogress.filecount += f.length
  uprogress.files = uprogress.files.concat(f)
  statNextFile()
}
let upqueue = [] as File[]

// TODO: Rewrite as WebSocket class
const WSCreate = async () => await new Promise<WebSocket>(resolve => {
  const ws = connect(uploadUrl, {
    open(ev: Event) { resolve(ws) },
    error(ev: Event) {
      console.error('Upload socket error', ev)
      documentStore.error = 'Upload socket error'
    },
    message(ev: MessageEvent) {
      const res = JSON.parse(ev!.data)
      if ('error' in res) {
        console.error('Upload socket error', res.error)
        documentStore.error = res.error.message
        return
      }
      if (res.status === 'ack') {
        statUpdate(res.req)
      } else console.log('Unknown upload response', res)
    },
  })
  // @ts-ignore
  ws.sendMsg = (msg: any) => ws.send(JSON.stringify(msg))
  // @ts-ignore
  ws.sendData = async (data: any) => {
    // Wait until the WS is ready to send another message
    uprogress.status = "uploading"
    await new Promise(resolve => {
      const t = setInterval(() => {
        if (ws.bufferedAmount > 1<<20) return
        resolve(undefined)
        clearInterval(t)
      }, 1)
    })
    uprogress.status = "processing"
    ws.send(data)
  }
})
const worker = async () => {
  const ws = await WSCreate()
  while (upqueue.length) {
    const f = upqueue[0]
    if (f.cloudPos === f.size) {
      upqueue.shift()
      continue
    }
    const start = f.cloudPos
    const end = Math.min(f.size, start + (1<<20))
    const control = { name: f.cloudName, size: f.size, start, end }
    const data = f.slice(start, end)
    f.cloudPos = end
    // Note: files may get modified during I/O
    ws.sendMsg(control)
    await ws.sendData(data)
  }
  if (upqueue.length) startWorker()
  uprogress.status = "idle"
  workerRunning = false
}
let workerRunning: any = false
const startWorker = () => {
  if (workerRunning === false) workerRunning = setTimeout(() => {
    workerRunning = true
    worker()
  }, 0)
}

onMounted(() => {
  // Need to prevent both to prevent browser from opening the file
  addEventListener('dragover', uploadHandler)
  addEventListener('drop', uploadHandler)
})
onUnmounted(() => {
  removeEventListener('dragover', uploadHandler)
  removeEventListener('drop', uploadHandler)
})
</script>
<template>
  <template>
    <input ref="fileInput" @change="uploadHandler" type="file" multiple>
    <input ref="folderInput" @change="uploadHandler" type="file" webkitdirectory>
  </template>
  <SvgButton name="add-file" data-tooltip="Upload files" @click="fileInput.click()" />
  <SvgButton name="add-folder" data-tooltip="Upload folder" @click="folderInput.click()" />
  <div class="uploadprogress" v-if="uprogress.total" :style="`background: linear-gradient(to right, var(--bar) 0, var(--bar) ${percent}%, var(--nobar) ${percent}%, var(--nobar) 100%);`">
    <div class="statustext">
      <span v-if="uprogress.filecount > 1" class="index">
        [{{ uprogress.fileidx }}/{{ uprogress.filecount }}]
      </span>
      <span class="filename">{{ uprogress.filename.split('/').pop() }}
        <span v-if="uprogress.filesize > 1e7" class="percent">
          {{ (uprogress.filepos / uprogress.filesize * 100).toFixed(0) + '\u202F%' }}
        </span>
      </span>
      <span class="position" v-if="uprogress.filesize > 1e7">
        {{ (uprogress.uploaded / 1e6).toFixed(0) + '\u202F/\u202F' + (uprogress.total / 1e6).toFixed(0) + '\u202FMB' }}
      </span>
      <span class="speed">{{ speeddisp }}</span>
      <button class="close" @click="cancelUploads">❌</button>
    </div>
  </div>
</template>

<style scoped>
.uploadprogress {
  --bar: var(--accent-color);
  --nobar: var(--header-background);
  display: flex;
  flex-direction: column;
  color: var(--primary-color);
  position: fixed;
  left: 0;
  bottom: 0;
  width: 100vw;
}
.statustext {
  display: flex;
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
</style>
