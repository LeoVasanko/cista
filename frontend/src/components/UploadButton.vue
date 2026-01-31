<template>
  <template>
    <input ref="fileInput" @change="uploadHandler" type="file" multiple>
    <input ref="folderInput" @change="uploadHandler" type="file" webkitdirectory>
  </template>
  <SvgButton name="add-file" data-tooltip="Upload files" @click="fileInput.click()" />
  <SvgButton name="add-folder" data-tooltip="Upload folder" @click="folderInput.click()" />
</template>

<script setup lang="ts">
import { connect, uploadUrl } from '@/repositories/WS';
import { useMainStore } from '@/stores/main'
import { collator } from '@/utils';
import { onMounted, onUnmounted, reactive, ref } from 'vue'

const fileInput = ref()
const folderInput = ref()
const store = useMainStore()
const props = defineProps({
  path: Array<string>
})

type CloudFile = {
  file: File
  cloudName: string
  cloudPos: number
}
function pasteHandler(event: ClipboardEvent) {
  const items = Array.from(event.clipboardData?.items ?? [])
  const infiles = [] as File[]
  const dirs = [] as FileSystemDirectoryEntry[]
  for (const item of items) {
    if (item.kind !== 'file') continue
    const entry = item.webkitGetAsEntry()
    if (entry?.isFile) {
      const file = item.getAsFile()
      if (file) infiles.push(file)
    } else if (entry?.isDirectory) {
      dirs.push(entry as FileSystemDirectoryEntry)
    }
  }
  if (infiles.length || dirs.length) {
    event.preventDefault()
    uploadFiles(infiles)
    for (const entry of dirs) pasteDirectory(entry, `${props.path!.join('/')}/${entry.name}`)
  }
}
const pasteDirectory = async (entry: FileSystemDirectoryEntry, loc: string) => {
  const reader = entry.createReader()
  const entries = await new Promise<any[]>(resolve => reader.readEntries(resolve))
  const cloudfiles = [] as CloudFile[]
  for (const entry of entries) {
    const cloudName = `${loc}/${entry.name}`
    if (entry.isFile) {
      const file = await new Promise(resolve => entry.file(resolve)) as File
      cloudfiles.push({file, cloudName, cloudPos: 0})
    } else if (entry.isDirectory) {
      await pasteDirectory(entry, cloudName)
    }
  }
  if (cloudfiles.length) uploadCloudFiles(cloudfiles)
}
function uploadHandler(event: Event) {
  event.preventDefault()
  // @ts-ignore
  const input = event.target as HTMLInputElement | null
  const infiles = Array.from((input ?? (event as DragEvent).dataTransfer)?.files ?? []) as File[]
  if (input) input.value = ''
  if (infiles.length) uploadFiles(infiles)
}

const uploadFiles = (infiles: File[]) => {
  const loc = props.path!.join('/')
  let files = []
  for (const file of infiles) {
    files.push({
      file,
      cloudName: loc + '/' + (file.webkitRelativePath || file.name),
      cloudPos: 0,
    })
  }
  uploadCloudFiles(files)
}
const uploadCloudFiles = (files: CloudFile[]) => {
  const dotfiles = files.filter(f => f.cloudName.includes('/.'))
  if (dotfiles.length) {
    store.showToast("Won't upload dotfiles")
    console.log("Dotfiles omitted", dotfiles)
    files = files.filter(f => !f.cloudName.includes('/.'))
  }
  if (!files.length) return
  files.sort((a, b) => collator.compare(a.cloudName, b.cloudName))
  // @ts-ignore
  upqueue = [...upqueue, ...files]
  statsAdd(files)
  startWorker()
}

const cancelUploads = () => {
  upqueue = []
  statReset()
}

const uprogress_init = {
  total: 0,
  xfer: 0,
  t0: 0,
  tlast: 0,
  statbytes: 0,
  statdur: 0,
  files: [] as CloudFile[],
  filestart: 0,
  fileidx: 0,
  filecount: 0,
  filename: '',
  filesize: 0,
  filepos: 0,
  status: 'idle',
}
store.uprogress = {...uprogress_init}
setInterval(() => {
  if (Date.now() - store.uprogress.tlast > 3000) {
    // Reset
    store.uprogress.statbytes = 0
    store.uprogress.statdur = 1
  } else {
    // Running average by decay
    store.uprogress.statbytes *= .9
    store.uprogress.statdur *= .9
  }
}, 100)
const statUpdate = ({name, size, start, end}: {name: string, size: number, start: number, end: number}) => {
  if (name !== store.uprogress.filename) return  // If stats have been reset
  const now = Date.now()
  store.uprogress.xfer = store.uprogress.filestart + end
  store.uprogress.filepos = end
  store.uprogress.statbytes += end - start
  store.uprogress.statdur += now - store.uprogress.tlast
  store.uprogress.tlast = now
  // File finished?
  if (end === size) {
    store.uprogress.filestart += size
    statNextFile()
    if (++store.uprogress.fileidx >= store.uprogress.filecount) statReset()
  }
}
const statNextFile = () => {
  const f = store.uprogress.files.shift()
  if (!f) return statReset()
  store.uprogress.filepos = 0
  store.uprogress.filesize = f.file.size
  store.uprogress.filename = f.cloudName
}
const statReset = () => {
  Object.assign(store.uprogress, uprogress_init)
  store.uprogress.t0 = Date.now()
  store.uprogress.tlast = store.uprogress.t0 + 1
}
const statsAdd = (f: CloudFile[]) => {
  if (store.uprogress.files.length === 0) statReset()
  store.uprogress.total += f.reduce((a, b) => a + b.file.size, 0)
  store.uprogress.filecount += f.length
  store.uprogress.files = [...store.uprogress.files, ...f]
  statNextFile()
}
let upqueue = [] as CloudFile[]

// TODO: Rewrite as WebSocket class
const WSCreate = async () => await new Promise<WebSocket>(resolve => {
  const ws = connect(uploadUrl, {
    open(ev: Event) { resolve(ws) },
    error(ev: Event) {
      console.error('Upload socket error', ev)
      store.error = 'Upload socket error'
    },
    message(ev: MessageEvent) {
      const res = JSON.parse(ev!.data)
      if ('error' in res) {
        console.error('Upload socket error', res.error)
        store.error = res.error.message
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
    store.uprogress.status = "uploading"
    await new Promise(resolve => {
      const t = setInterval(() => {
        if (ws.bufferedAmount > 1<<20) return
        resolve(undefined)
        clearInterval(t)
      }, 1)
    })
    store.uprogress.status = "processing"
    ws.send(data)
  }
})
const worker = async () => {
  const ws = await WSCreate()
  while (upqueue.length) {
    const f = upqueue[0]!
    const start = f.cloudPos
    const end = Math.min(f.file.size, start + (1<<20))
    const control = { name: f.cloudName, size: f.file.size, start, end }
    const data = f.file.slice(start, end)
    f.cloudPos = end
    // Note: files may get modified during I/O
    // @ts-ignore FIXME proper WebSocket class, avoid attaching functions to WebSocket object
    ws.sendMsg(control)
    // @ts-ignore
    await ws.sendData(data)
    if (f.cloudPos === f.file.size) upqueue.shift()
  }
  if (upqueue.length) startWorker()
  store.uprogress.status = "idle"
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
  addEventListener('paste', pasteHandler)
})
onUnmounted(() => {
  removeEventListener('paste', pasteHandler)
  removeEventListener('dragover', uploadHandler)
  removeEventListener('drop', uploadHandler)
})
</script>
