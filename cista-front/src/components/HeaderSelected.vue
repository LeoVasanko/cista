<template>
  <template v-if="documentStore.selected.size">
    <div class="smallgap"></div>
    <p class="select-text">{{ documentStore.selected.size }} selected ➤</p>
    <SvgButton name="download" data-tooltip="Download" @click="download" />
    <SvgButton name="copy" data-tooltip="Copy here" @click="op('cp', dst)" />
    <SvgButton name="paste" data-tooltip="Move here" @click="op('mv', dst)" />
    <SvgButton name="trash" data-tooltip="Delete ⚠️" @click="op('rm')" />
    <button class="action-button unselect" data-tooltip="Unselect all" @click="documentStore.selected.clear()">❌</button>
  </template>
</template>

<script setup lang="ts">
import {connect, controlUrl} from '@/repositories/WS'
import { useDocumentStore } from '@/stores/documents'
import { computed } from 'vue'
import type { SelectedItems } from '@/repositories/Document'

const documentStore = useDocumentStore()
const props = defineProps({
  path: Array<string>
})

const dst = computed(() => props.path!.join('/'))
const op = (op: string, dst?: string) => {
  const sel = documentStore.selectedFiles
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
    message(ev: WebSocmetMessageEvent) {
      const res = JSON.parse(ev.data)
      if ('error' in res) {
        console.error('Control socket error', msg, res.error)
        documentStore.error = res.error.message
        return
      } else if (res.status === 'ack') {
        console.log('Control ack OK', res)
        control.close()
        documentStore.selected.clear()
        return
      } else console.log('Unknown control response', msg, res)
    }
  })
  control.onopen = () => {
    control.send(JSON.stringify(msg))
  }
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
    if (!res.ok)
      throw new Error(`Failed to download ${url}: ${res.status} ${res.statusText}`)
    if (res.body) await res.body.pipeTo(writable)
    else {
      // Zero-sized files don't have a body, so we need to create an empty file
      await writable.truncate(0)
      await writable.close()
    }
    console.log('Saved', hdir + name)
  }
}

const download = async () => {
  const sel = documentStore.selectedFiles
  console.log('Download', sel)
  if (sel.keys.length === 0) {
    console.warn('Attempted download but no files found. Missing selected keys:', sel.missing)
    documentStore.selected.clear()
    return
  }
  // Plain old a href download if only one file (ignoring any folders)
  const files = sel.recursive.filter(([rel, full, doc]) => !doc.dir)
  if (files.length === 1) {
    documentStore.selected.clear()
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
      filesystemdl(sel, handle).then(() => {
        documentStore.selected.clear()
      })
      return
    } catch (e) {
      console.error('Download to folder aborted', e)
    }
  }
  // Otherwise, zip and download
  const name = sel.keys.length === 1 ? sel.docs[sel.keys[0]].name : 'download'
  linkdl(`/zip/${Array.from(sel.keys).join('+')}/${name}.zip`)
  documentStore.selected.clear()
}
</script>

<style>
.select-text {
  color: var(--accent-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
