<template>
  <SvgButton name="download" data-tooltip="Download" @click="download" />
  <TransferBar :status=progress @cancel=cancelDownloads />
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import type { SelectedItems } from '@/repositories/Document'
import { reactive } from 'vue';

const store = useMainStore()

const status_init = {
  total: 0,
  xfer: 0,
  t0: 0,
  tlast: 0,
  statbytes: 0,
  statdur: 0,
  files: [] as string[],
  filestart: 0,
  fileidx: 0,
  filecount: 0,
  filename: '',
  filesize: 0,
  filepos: 0,
  status: 'idle',
}
const progress = reactive({...status_init})
setInterval(() => {
  if (Date.now() - progress.tlast > 3000) {
    // Reset
    progress.statbytes = 0
    progress.statdur = 1
  } else {
    // Running average by decay
    progress.statbytes *= .9
    progress.statdur *= .9
  }
}, 100)
const statReset = () => {
  Object.assign(progress, status_init)
  progress.t0 = Date.now()
  progress.tlast = progress.t0 + 1
}
const cancelDownloads = () => {
  location.reload()  // FIXME
}


const linkdl = (href: string) => {
  const a = document.createElement('a')
  a.href = href
  a.download = ''
  a.click()
}

const filesystemdl = async (sel: SelectedItems, handle: FileSystemDirectoryHandle) => {
  let hdir = ''
  let h = handle
  console.log('Downloading to filesystem', sel.recursive)
  for (const [rel, full, doc] of sel.recursive) {
    if (doc.dir) continue
    progress.files.push(rel)
    ++progress.filecount
    progress.total += doc.size
  }
  for (const [rel, full, doc] of sel.recursive) {
    // Create any missing directories
    if (hdir && !rel.startsWith(hdir + '/')) {
      hdir = ''
      h = handle
    }
    const r = rel.slice(hdir.length)
    for (const dir of r.split('/').slice(0, doc.dir ? undefined : -1)) {
      hdir += `${dir}/`
      try {
        h = await h.getDirectoryHandle(dir.normalize('NFC'), { create: true })
      } catch (error) {
        console.error('Failed to create directory', hdir, error)
        return
      }
      console.log('Created', hdir)
    }
    if (doc.dir) continue // Target was a folder and was created
    const name = rel.split('/').pop()!.normalize('NFC')
    // Download file
    let fileHandle
    try {
      fileHandle = await h.getFileHandle(name, { create: true })
    } catch (error) {
      console.error('Failed to create file', rel, full, hdir + name, error)
      return
    }
    const writable = await fileHandle.createWritable()
    const url = `/files/${rel}`
    console.log('Fetching', url)
    const res = await fetch(url)
    if (!res.ok) {
      store.error = `Failed to download ${url}: ${res.status} ${res.statusText}`
      throw new Error(`Failed to download ${url}: ${res.status} ${res.statusText}`)
    }
    if (res.body) {
      ++progress.fileidx
      const reader = res.body.getReader()
      await writable.truncate(0)
      store.error = "Direct download."
      progress.tlast = Date.now()
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        await writable.write(value)
        const now = Date.now()
        const size = value.byteLength
        progress.xfer += size
        progress.filepos += size
        progress.statbytes += size
        progress.statdur += now - progress.tlast
        progress.tlast = now
      }
    }
    await writable.close()
    console.log('Saved', hdir + name)
  }
  statReset()
}

const download = async () => {
  const sel = store.selectedFiles
  console.log('Download', sel)
  if (sel.keys.length === 0) {
    console.warn('Attempted download but no files found. Missing selected keys:', sel.missing)
    store.error = 'No existing files selected'
    store.selected.clear()
    return
  }
  // Plain old a href download if only one file (ignoring any folders)
  const files = sel.recursive.filter(([rel, full, doc]) => !doc.dir)
  if (files.length === 1) {
    store.selected.clear()
    store.error = "Single file via browser downloads"
    return linkdl(`/files/${files[0][1]}`)
  }
  // Use FileSystem API if multiple files and the browser supports it
  if ('showDirectoryPicker' in window) {
    try {
      // @ts-ignore
      const handle = await window.showDirectoryPicker({
        startIn: 'downloads',
        mode: 'readwrite'
      })
      await filesystemdl(sel, handle)
      store.selected.clear()
      return
    } catch (e) {
      console.error('Download to folder aborted', e)
    }
  }
  // Otherwise, zip and download
  console.log("Falling back to zip download")
  const name = sel.keys.length === 1 ? sel.docs[sel.keys[0]].name : 'download'
  linkdl(`/zip/${Array.from(sel.keys).join('+')}/${name}.zip`)
  store.error = "Downloading as ZIP via browser downloads"
  store.selected.clear()
}

</script>

<style scoped>

</style>
