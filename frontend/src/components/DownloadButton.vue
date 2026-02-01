<template>
  <SvgButton name="download" data-tooltip="Download" @click="download" />
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import { apiFetch } from '@/repositories/Client'
import type { SelectedItems } from '@/repositories/Document'
import { zipName } from '@/utils/fileutil'

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
store.dprogress = {...status_init}
setInterval(() => {
  if (Date.now() - store.dprogress.tlast > 3000) {
    // Reset
    store.dprogress.statbytes = 0
    store.dprogress.statdur = 1
  } else {
    // Running average by decay
    store.dprogress.statbytes *= .9
    store.dprogress.statdur *= .9
  }
}, 100)
const statReset = () => {
  Object.assign(store.dprogress, status_init)
  store.dprogress.t0 = Date.now()
  store.dprogress.tlast = store.dprogress.t0 + 1
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
    store.dprogress.files.push(rel)
    ++store.dprogress.filecount
    store.dprogress.total += doc.size
  }
  for (const [rel, full, doc] of sel.recursive) {
    // Create any missing directories
    if (hdir && !rel.startsWith(hdir + '/')) {
      hdir = ''
      h = handle
    }
    const r = rel.slice(hdir.length)
    for (const dir of r.split('/').slice(0, doc.dir ? undefined : -1)) {
      if (!dir) continue
      hdir += `${dir}/`
      try {
        h = await h.getDirectoryHandle(dir.normalize('NFC'), { create: true })
      } catch (error) {
        console.error('Failed to create directory', hdir, error)
        throw new Error(`Failed to create directory ${hdir}: ${error}`)
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
      throw new Error(`Failed to create file ${hdir + name}: ${error}`)
    }
    try {
      const writable = await fileHandle.createWritable()
      const url = `/files/${rel}`
      console.log('Fetching', url)
      const res = await apiFetch(url)
      if (!res.ok) {
        store.error = `Failed to download ${url}: ${res.status} ${res.statusText}`
        throw new Error(`Failed to download ${url}: ${res.status} ${res.statusText}`)
      }
      if (res.body) {
        ++store.dprogress.fileidx
        const reader = res.body.getReader()
        await writable.truncate(0)
        store.dprogress.tlast = Date.now()
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          await writable.write(value)
          const now = Date.now()
          const size = value.byteLength
          store.dprogress.xfer += size
          store.dprogress.filepos += size
          store.dprogress.statbytes += size
          store.dprogress.statdur += now - store.dprogress.tlast
          store.dprogress.tlast = now
        }
      }
      await writable.close()
      console.log('Saved', hdir + name)
    } catch (error) {
      console.error('Failed to write file', hdir + name, error)
      throw new Error(`Failed to write file ${hdir + name}: ${error}`)
    }
  }
  statReset()
}

const zipdl = (sel: SelectedItems) => {
  const items = sel.keys.map(k => sel.docs[k]!)
  const name = zipName(items)
  linkdl(`/zip/${Array.from(sel.keys).join('+')}/${name}.zip`)
  store.showToast(`Downloading ${name}.zip`)
  store.selected.clear()
}

const download = async (e: MouseEvent) => {
  const sel = store.selectedFiles
  if (sel.keys.length === 0) {
    store.showToast('No existing files selected')
    store.selected.clear()
    return
  }
  // Single file: direct download
  const files = sel.recursive.filter(([rel, full, doc]) => !doc.dir)
  if (files.length === 1) {
    store.selected.clear()
    store.showToast(`Downloading ${files[0]![0].split('/').pop()}`)
    return linkdl(`/files/${files[0]![1]}`)
  }
  // Alt+click: download to folder (hidden feature)
  if (e.altKey && 'showDirectoryPicker' in window) {
    try {
      // @ts-ignore
      const handle = await window.showDirectoryPicker({ startIn: 'downloads', mode: 'readwrite' })
      await filesystemdl(sel, handle)
      store.selected.clear()
    } catch (e) {
      console.error('Download to folder failed', e)
      store.showToast('Download to folder failed')
    }
    return
  }
  // Default: ZIP download
  zipdl(sel)
}

</script>

<style scoped>

</style>
