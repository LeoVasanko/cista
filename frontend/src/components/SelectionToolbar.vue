<template>
  <div class="selection-bar" v-if="store.selected.size">
    <div class="select-info">
      <template v-if="selectionDisplay.folders.length <= 5">
        <span class="select-folders">
          <template v-for="(folder, i) in selectionDisplay.folders" :key="folder.path">
            <span v-if="i > 0" class="folder-sep">, </span>
            <a :href="'/#/' + folder.path" class="folder-link" @click.prevent="navigateTo(folder.path)">{{ folder.name }}</a>
          </template>
        </span>
      </template>
      <template v-else>
        <span class="select-count">{{ store.selected.size }} items from {{ selectionDisplay.numFolders }} folders</span>
      </template>
    </div>
    <span class="select-size">{{ selectionDisplay.size }}</span>
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
    >✖ selection</button>
  </div>
</template>

<script setup lang="ts">
import { apiFetch } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'
import { computed, ref } from 'vue'
import { formatSize } from '@/utils'
import CursorTooltip from './CursorTooltip.vue'
import router from '@/router'

const unselectTooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)

const store = useMainStore()
const props = defineProps({
  path: Array<string>
})

const dst = computed(() => props.path!.join('/'))

const navigateTo = (path: string) => {
  router.push('/' + path)
}

const filesUrl = (path: string) =>
  '/files/' + path.split('/').map(part => encodeURIComponent(part)).join('/')

const parseErrorMessage = async (res: Response) => {
  try {
    const data = await res.json()
    return data.message || data.detail || `${res.status} ${res.statusText}`
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

// Truncate long names to reasonable length
const truncateName = (name: string, maxLen = 20): string => {
  if (name.length <= maxLen) return name
  return name.slice(0, maxLen - 1) + '…'
}

interface FolderInfo {
  name: string
  path: string
  count: number
}

interface SelectionDisplay {
  folders: FolderInfo[]
  numFolders: number
  size: string
}

const selectionDisplay = computed<SelectionDisplay>(() => {
  const sel = store.selectedFiles

  // Calculate total size
  const totalSize = sel.keys.reduce((sum, key) => {
    const doc = sel.docs[key]
    return sum + (doc ? doc.size : 0)
  }, 0)
  const sizeStr = formatSize(totalSize)

  // Group by folder location, storing file names
  const folderGroups = new Map<string, string[]>()
  for (const key of sel.keys) {
    const doc = sel.docs[key]
    if (!doc) continue
    const loc = doc.loc || ''
    if (!folderGroups.has(loc)) folderGroups.set(loc, [])
    folderGroups.get(loc)!.push(doc.name)
  }

  const numFolders = folderGroups.size

  const folders = Array.from(folderGroups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([loc, names]) => {
      const count = names.length
      // For single file, display truncated filename; for multiple, display folder name with count
      let displayName: string
      if (count === 1) {
        displayName = truncateName(names[0]!)
      } else {
        const folderName = loc ? loc.split('/').pop()! : (store.server.name || 'Root')
        displayName = `${truncateName(folderName)} (${count})`
      }
      return {
        name: displayName,
        path: loc,
        count
      }
    })

  return {
    folders,
    numFolders,
    size: sizeStr
  }
})

const op = async (opName: string, dst?: string) => {
  const sel = store.selectedFiles
  const keys = sel.keys
  const paths = sel.keys.map(key => {
    const doc = sel.docs[key]!
    return doc.loc ? `${doc.loc}/${doc.name}` : doc.name
  })

  // Hide items being deleted or moved (optimistic update)
  if (opName === 'rm' || opName === 'mv') {
    for (const path of paths) store.hideDoc(path)
  }

  try {
    if (opName === 'rm') {
      for (const path of paths) {
        const res = await apiFetch(filesUrl(path), { method: 'DELETE' })
        if (!res.ok) throw new Error(await parseErrorMessage(res))
      }
    } else if (opName === 'mv' || opName === 'cp') {
      if (keys.length === 0) throw new Error('No selected files')
      const dstUrl = dst ? filesUrl(dst) : '/files/'
      const query = `${opName}=${keys.join('+')}`
      const res = await apiFetch(`${dstUrl}?${query}`, { method: 'POST' })
      if (!res.ok) throw new Error(await parseErrorMessage(res))
    } else {
      throw new Error(`Unsupported operation: ${opName}`)
    }

    store.selected.clear()
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.error('REST file operation failed', opName, err)
    store.error = message
    if (opName === 'rm' || opName === 'mv') {
      for (const path of paths) store.unhideDoc(path)
    }
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
  font-size: var(--header-font-size);
  gap: 0.3em;
  flex-wrap: nowrap;
  max-width: 100%;
}
.select-info {
  color: var(--accent-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0;
  flex-shrink: 1;
  min-width: 0;
}
.select-count {
  font-weight: 500;
}
.select-folders {
  display: inline;
}
.folder-link,
.folder-link:link,
.folder-link:visited,
.folder-link:active {
  color: var(--accent-color);
  text-decoration: none;
  cursor: pointer;
}
.folder-link:hover {
  text-decoration: underline;
  color: var(--accent-color);
}
.folder-sep {
  color: var(--header-color);
  opacity: 0.6;
}
.select-size {
  color: var(--header-color);
  opacity: 0.8;
  font-family: 'Roboto Mono', monospace;
  font-size: 0.9em;
  margin-left: 0.5em;
}
</style>
