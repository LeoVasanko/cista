<template>
  <template>
    <input ref="fileInput" @change="uploadHandler" type="file" multiple>
    <input ref="folderInput" @change="uploadHandler" type="file" webkitdirectory>
  </template>
  <SvgButton name="add-file" tooltip="Upload files" @click="fileInput.click()" />
  <SvgButton name="add-folder" tooltip="Upload folder" @click="folderInput.click()" />
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { getDocuments } from '@/stores/documentStore'
import { useMainStore } from '@/stores/main'
import { collator, formatSize } from '@/utils'
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
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

type UploadRange = {
  name: string
  size: number
  start: number
  end: number
}

type InflightBlock = {
  name: string
  start: number
  end: number
  startedAt: number
}

const UPLOAD_BLOCK_SIZE = 16 << 20 // 16 MiB
const UPLOAD_MARGIN_BYTES = 512 * 1024 * 1024 // 512 MiB
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
    const base = props.path!.join('/')
    for (const entry of dirs)
      pasteDirectory(entry, `${base ? `${base}/` : ''}${entry.name}`)
  }
}
const pasteDirectory = async (entry: FileSystemDirectoryEntry, loc: string) => {
  const reader = entry.createReader()
  const entries = await new Promise<any[]>(resolve => reader.readEntries(resolve))
  const cloudfiles = [] as CloudFile[]
  for (const entry of entries) {
    const cloudName = `${loc}/${entry.name}`
    if (entry.isFile) {
      const file = (await new Promise(resolve => entry.file(resolve))) as File
      cloudfiles.push({ file, cloudName, cloudPos: 0 })
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
  const infiles = Array.from(
    (input ?? (event as DragEvent).dataTransfer)?.files ?? []
  ) as File[]
  if (input) input.value = ''
  if (infiles.length) uploadFiles(infiles)
}

const uploadFiles = (infiles: File[]) => {
  const loc = props.path!.join('/')
  let files = []
  let folderName = ''
  for (const file of infiles) {
    const relPath = file.webkitRelativePath || file.name
    if (!folderName && file.webkitRelativePath) folderName = relPath.split('/')[0] ?? ''
    files.push({
      file,
      cloudName: `${loc ? `${loc}/` : ''}${relPath}`,
      cloudPos: 0
    })
  }
  uploadCloudFiles(files)
  if (folderName) router.push('/' + (loc ? loc + '/' : '') + folderName + '/')
}
const uploadCloudFiles = (files: CloudFile[]) => {
  const dotfiles = files.filter(f => f.cloudName.includes('/.'))
  if (dotfiles.length) {
    store.showToast("Won't upload dotfiles")
    files = files.filter(f => !f.cloudName.includes('/.'))
  }
  if (!files.length) return
  files.sort((a, b) => collator.compare(a.cloudName, b.cloudName))

  // Space check: reject the whole batch if there isn't enough free space.
  const batchTotal = files.reduce((sum, f) => sum + f.file.size, 0)
  const allDocs = getDocuments()
  const docByPath = new Map<string, Doc>()
  for (const d of allDocs) {
    const path = d.loc ? `${d.loc}/${d.name}` : d.name
    docByPath.set(path, d)
  }
  let overwriteSize = 0
  for (const f of files) {
    const existing = docByPath.get(f.cloudName)
    if (existing && !existing.dir) overwriteSize += existing.size
  }
  const netNeed = batchTotal - overwriteSize
  if (store.space.free < netNeed + UPLOAD_MARGIN_BYTES) {
    store.showToast(
      `Not enough free space (need ${formatSize(netNeed + UPLOAD_MARGIN_BYTES)}, have ${formatSize(store.space.free)})`
    )
    return
  }

  // Optimistic update: ghost folders and files
  const now = Math.floor(Date.now() / 1000)
  const docs = getDocuments()
  const byPath = new Map(docs.map(d => [d.loc ? `${d.loc}/${d.name}` : d.name, d]))
  // Also check existing ghosts
  for (const g of store.ghosts) {
    byPath.set(g.loc ? `${g.loc}/${g.name}` : g.name, g)
  }
  const added = new Set<string>()
  for (const f of files) {
    const lastSlash = f.cloudName.lastIndexOf('/')
    const loc = lastSlash > 0 ? f.cloudName.slice(0, lastSlash) : ''
    const name = f.cloudName.slice(lastSlash + 1)
    // Ghost folders for intermediate directories
    const parts = loc.split('/')
    for (let i = 0; i < parts.length; i++) {
      const folderPath = parts.slice(0, i + 1).join('/')
      if (folderPath && !byPath.has(folderPath) && !added.has(folderPath)) {
        store.addGhost(
          new Doc({
            loc: parts.slice(0, i).join('/'),
            name: parts[i],
            key: crypto.randomUUID(),
            size: 0,
            allocated: 0,
            mtime: now,
            dir: true
          })
        )
        added.add(folderPath)
      }
    }
    // Ghost file or update existing (overwrite case doesn't need ghost, file already visible)
    const existing = byPath.get(f.cloudName)
    if (!existing)
      store.addGhost(
        new Doc({
          loc,
          name,
          key: crypto.randomUUID(),
          size: f.file.size,
          allocated: 0,
          mtime: now,
          dir: false
        })
      )
  }
  // @ts-ignore
  upqueue = [...upqueue, ...files]
  statsAdd(files)
  startWorker()
}

const cancelUploads = () => {
  uploadRunId += 1
  upqueue = []
  blockQueue = []
  inflightBlocks.clear()
  uploadedBytes.clear()
  store.uprogress.status = 'idle'
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
  status: 'idle'
}
store.uprogress = { ...uprogress_init }
// Track uploaded bytes for each file to handle out-of-order uploads
const uploadedBytes = new Map<string, Set<number>>()
const inflightBlocks = new Map<string, InflightBlock>()
let smoothedBlockMs = 1500
let lastProgressTick = Date.now()
let lastVisualUploaded = 0

const inflightKey = (name: string, start: number) => `${name}:${start}`

const completedUploadedBytes = (name: string, size: number) => {
  const uploaded = uploadedBytes.get(name)
  if (!uploaded) return 0
  const blockSize = UPLOAD_BLOCK_SIZE
  let total = 0
  for (let i = 0; i < size; i += blockSize) {
    if (uploaded.has(i)) total += Math.min(blockSize, size - i)
  }
  return total
}

const simulatedInflightBytes = (name: string, now: number) => {
  let total = 0
  for (const block of inflightBlocks.values()) {
    if (block.name !== name) continue
    const size = block.end - block.start
    const elapsed = Math.max(0, now - block.startedAt)
    const fraction = Math.min(0.98, elapsed / Math.max(200, smoothedBlockMs))
    total += size * fraction
  }
  return total
}

const refreshProgress = (now: number) => {
  const name = store.uprogress.filename
  const size = store.uprogress.filesize
  if (!name || !size) {
    lastProgressTick = now
    return 0
  }

  const completed = completedUploadedBytes(name, size)
  const estimated = simulatedInflightBytes(name, now)
  const visualUploaded = Math.min(size, Math.round(completed + estimated))
  const delta = Math.max(0, visualUploaded - lastVisualUploaded)
  const dt = Math.max(1, now - lastProgressTick)

  store.uprogress.filepos = visualUploaded
  store.uprogress.xfer = store.uprogress.filestart + visualUploaded

  if (delta > 0) {
    store.uprogress.statbytes += delta
    store.uprogress.statdur += dt
    store.uprogress.tlast = now
  }

  lastVisualUploaded = visualUploaded
  lastProgressTick = now
  return delta
}

setInterval(() => {
  const now = Date.now()
  const delta = refreshProgress(now)
  if (delta > 0) return
  if (now - store.uprogress.tlast > 3000) {
    store.uprogress.statbytes = 0
    store.uprogress.statdur = 1
  } else {
    store.uprogress.statbytes *= 0.95
    store.uprogress.statdur *= 0.95
  }
}, 100)

const statUpdate = ({ name, size, start, end }: UploadRange) => {
  if (name !== store.uprogress.filename) return // If stats have been reset

  // Track which bytes have been uploaded (using start to end range)
  if (!uploadedBytes.has(name)) uploadedBytes.set(name, new Set())
  const uploaded = uploadedBytes.get(name)!
  const blockSize = UPLOAD_BLOCK_SIZE

  // Mark all bytes in this block as uploaded
  for (let i = start; i < end; i += blockSize) {
    uploaded.add(i)
  }
  refreshProgress(Date.now())

  // Check if file is fully uploaded by examining the block queue
  const currentUpload = blockQueue[0]
  if (!currentUpload) return

  if (
    currentUpload.file.cloudName === name &&
    currentUpload.completed >= currentUpload.blocks.length
  ) {
    // All blocks for this file have been uploaded
    uploadedBytes.delete(name) // Clean up tracking
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
  lastVisualUploaded = 0
  lastProgressTick = Date.now()
}
const statReset = () => {
  Object.assign(store.uprogress, uprogress_init)
  store.uprogress.t0 = Date.now()
  store.uprogress.tlast = store.uprogress.t0 + 1
  lastVisualUploaded = 0
  lastProgressTick = store.uprogress.t0
}
const statsAdd = (f: CloudFile[]) => {
  if (store.uprogress.files.length === 0) statReset()
  store.uprogress.total += f.reduce((a, b) => a + b.file.size, 0)
  store.uprogress.filecount += f.length
  store.uprogress.files = [...store.uprogress.files, ...f]
  statNextFile()
}
let upqueue = [] as CloudFile[]
const MAX_PARALLEL_REQUESTS = 4
const RETRY_DELAY_MS = 400

// Helper function to get upload blocks for a file, prioritizing final 4 blocks if file >= 32 MiB
const getUploadBlocks = (file: CloudFile): { start: number; end: number }[] => {
  const BLOCK_SIZE = UPLOAD_BLOCK_SIZE
  const MIN_SIZE_FOR_REORDER = 32 * BLOCK_SIZE // 32 MiB = 33554432 bytes
  const FINAL_BLOCKS_COUNT = 2

  const fileSize = file.file.size
  const blocks: { start: number; end: number }[] = []

  if (fileSize >= MIN_SIZE_FOR_REORDER) {
    // File is large enough, prioritize final blocks
    const finalBlocksStart = fileSize - FINAL_BLOCKS_COUNT * BLOCK_SIZE

    // Add final blocks first
    for (let i = 0; i < FINAL_BLOCKS_COUNT; i++) {
      const start = finalBlocksStart + i * BLOCK_SIZE
      const end = Math.min(start + BLOCK_SIZE, fileSize)
      blocks.push({ start, end })
    }

    // Add remaining blocks from beginning
    for (let start = 0; start < finalBlocksStart; start += BLOCK_SIZE) {
      const end = Math.min(start + BLOCK_SIZE, finalBlocksStart)
      blocks.push({ start, end })
    }
  } else {
    // File is smaller, use sequential upload
    for (let start = 0; start < fileSize; start += BLOCK_SIZE) {
      const end = Math.min(start + BLOCK_SIZE, fileSize)
      blocks.push({ start, end })
    }
  }

  return blocks
}

type BlockUpload = {
  file: CloudFile
  blocks: { start: number; end: number }[]
  nextIndex: number
  completed: number
  runId: number
}

let blockQueue = [] as BlockUpload[]
let workerRunning = false
let uploadRunId = 0

const enqueuePendingUploads = () => {
  while (upqueue.length) {
    const file = upqueue.shift()!
    const blocks = getUploadBlocks(file)
    blockQueue.push({ file, blocks, nextIndex: 0, completed: 0, runId: uploadRunId })
  }
}

const uploadUrlForFile = (cloudName: string) => {
  const normalized = cloudName.replace(/^\/+/, '')
  const encoded = normalized.split('/').map(encodeURIComponent).join('/')
  return `/files/${encoded}`
}

const uploadBlock = async (
  upload: BlockUpload,
  block: { start: number; end: number }
) => {
  const body = upload.file.file.slice(block.start, block.end)
  const range = `bytes ${block.start}-${block.end - 1}/${upload.file.file.size}`
  const fallbackReq = {
    name: upload.file.cloudName,
    size: upload.file.file.size,
    start: block.start,
    end: block.end
  }
  let attempt = 0

  while (true) {
    attempt += 1
    if (upload.runId !== uploadRunId) throw new Error('Upload cancelled')
    try {
      const res = await fetch(uploadUrlForFile(upload.file.cloudName), {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Range': range
        },
        body
      })
      if (!res.ok) {
        const message = await res.text().catch(() => '')
        const retryable = res.status >= 500 || res.status === 408 || res.status === 429
        if (!retryable) throw new Error(message || `HTTP ${res.status}`)
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS))
        continue
      }
      const payload = await res.json().catch(() => null)
      return payload?.status === 'ack' && payload.req ? payload.req : fallbackReq
    } catch (err: any) {
      const message = err instanceof Error ? err.message : String(err)
      if (message === 'Upload cancelled') throw err
      if (upload.runId !== uploadRunId) throw new Error('Upload cancelled')
      if (attempt % 10 === 0) {
        console.warn(`Upload retry ${attempt} for ${upload.file.cloudName}: ${message}`)
      }
      await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS))
    }
  }
}

const startInflightBlock = (name: string, block: { start: number; end: number }) => {
  inflightBlocks.set(inflightKey(name, block.start), {
    name,
    start: block.start,
    end: block.end,
    startedAt: Date.now()
  })
}

const finishInflightBlock = (name: string, block: { start: number; end: number }) => {
  const key = inflightKey(name, block.start)
  const info = inflightBlocks.get(key)
  if (!info) return
  const elapsed = Math.max(1, Date.now() - info.startedAt)
  smoothedBlockMs = smoothedBlockMs * 0.85 + elapsed * 0.15
  inflightBlocks.delete(key)
}

const worker = async (runId: number) => {
  try {
    while (runId === uploadRunId) {
      enqueuePendingUploads()
      if (!blockQueue.length) break

      const upload = blockQueue[0]!
      const inflight = new Set<Promise<void>>()

      while (runId === uploadRunId && upload.completed < upload.blocks.length) {
        while (
          runId === uploadRunId &&
          upload.nextIndex < upload.blocks.length &&
          inflight.size < MAX_PARALLEL_REQUESTS
        ) {
          const block = upload.blocks[upload.nextIndex++]!
          store.uprogress.status = 'uploading'
          startInflightBlock(upload.file.cloudName, block)
          let task: Promise<void>
          task = uploadBlock(upload, block)
            .then(req => {
              finishInflightBlock(upload.file.cloudName, block)
              upload.completed += 1
              statUpdate(req)
            })
            .catch(err => {
              finishInflightBlock(upload.file.cloudName, block)
              throw err
            })
            .finally(() => {
              inflight.delete(task)
            })
          inflight.add(task)
        }

        if (!inflight.size) break
        await Promise.race(inflight)
      }

      if (runId !== uploadRunId) return

      if (upload.completed >= upload.blocks.length) {
        blockQueue.shift()
      } else {
        break
      }
    }
  } catch (err: any) {
    if (runId !== uploadRunId) return
    console.error('Upload error', err)
    store.error = err?.message || 'Upload failed'
    uploadRunId += 1
    upqueue = []
    blockQueue = []
    inflightBlocks.clear()
  } finally {
    store.uprogress.status = 'idle'
    workerRunning = false
    if (upqueue.length) startWorker()
  }
}

const startWorker = () => {
  if (workerRunning) return
  workerRunning = true
  const runId = uploadRunId
  setTimeout(() => {
    void worker(runId)
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
