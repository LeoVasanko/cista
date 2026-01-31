import type { FileEntry, FUID, SelectedItems } from '@/repositories/Document'
import { Doc } from '@/repositories/Document'
import { defineStore, type StateTree } from 'pinia'
import { collator } from '@/utils'
import { watchConnect, resumeWatching } from '@/repositories/WS'
import { sorted, type SortOrder } from '@/utils/docsort'
import SearchWorker from '@/workers/searchWorker?worker'

// Singleton search worker instance
let searchWorker: Worker | null = null
let searchId = 0
let searchStore: ReturnType<typeof useMainStore> | null = null

function getSearchWorker(): Worker {
  if (!searchWorker) {
    searchWorker = new SearchWorker()
    // Set up message handler once
    searchWorker.onmessage = (e) => {
      if (!searchStore || e.data.id !== searchId) return  // Stale result

      // Convert plain data back to Doc instances (constructor is now lightweight)
      const docs = []
      for (const d of e.data.docs) {
        docs.push(new Doc(d))
      }
      searchStore.searchResults = docs

      if (e.data.done) {
        searchStore.searchLoading = false
      }
    }
  }
  return searchWorker
}

export const useMainStore = defineStore('main', {
  state: () => ({
    document: [] as Doc[],
    selected: new Set<FUID>([]),
    query: '' as string,
    searchResults: [] as Doc[],
    searchLoading: false,
    _searchRouteTimer: null as ReturnType<typeof setTimeout> | null,
    fileExplorer: null as any,
    error: '' as string,  // Permanent status message (e.g., "Reconnecting...")
    toast: '' as string,  // Temporary toast (auto-dismisses)
    toastTimeout: null as ReturnType<typeof setTimeout> | null,
    connected: false,
    authInProgress: false,
    cursor: '' as string,
    server: {} as Record<string, any> & { public?: boolean, paskia?: boolean },
    dialog: '' as '' | 'settings' | 'usermgmt' | 'accessdenied',
    uprogress: {} as any,
    dprogress: {} as any,
    prefs: {
      gallery: false,
      sortListing: '' as SortOrder,
      sortFiltered: '' as SortOrder,
    },
    user: {
      username: '' as string,
      privileged: false as boolean,
      isLoggedIn: false as boolean,
    }
  }),
  persist: {
    pick: ['prefs', 'cursor', 'selected'],
    serializer: {
      deserialize: (data: string): StateTree => {
        const ret = JSON.parse(data)
        ret.selected = new Set(ret.selected)
        return ret
      },
      serialize: (tree: StateTree): string => {
        tree.selected = Array.from(tree.selected)
        return JSON.stringify(tree)
      }
    },
  },
  actions: {
    updateRoot(root: FileEntry[]) {
      const docs = []
      let loc = [] as string[]
      for (const [level, name, key, mtime, size, isfile] of root) {
        loc = loc.slice(0, level - 1)
        docs.push(new Doc({
          name,
          loc: level ? loc.join('/') : '/',
          key,
          size,
          mtime,
          dir: !isfile,
        }))
        loc.push(name)
      }
      this.document = docs
      // Sync documents to search worker
      this.syncSearchWorker()
    },
    /** Show a temporary toast message that auto-dismisses */
    showToast(message: string, duration = 3000) {
      if (this.toastTimeout) {
        clearTimeout(this.toastTimeout)
        this.toastTimeout = null
      }
      this.toast = message
      this.toastTimeout = setTimeout(() => {
        this.toast = ''
        this.toastTimeout = null
      }, duration)
    },
    /** Clear the current toast immediately */
    clearToast() {
      if (this.toastTimeout) {
        clearTimeout(this.toastTimeout)
        this.toastTimeout = null
      }
      this.toast = ''
    },
    syncSearchWorker() {
      const worker = getSearchWorker()
      // Send plain data to worker (no class instances)
      const docData = this.document.map(doc => ({
        loc: doc.loc,
        name: doc.name,
        key: doc.key,
        size: doc.size,
        mtime: doc.mtime,
        dir: doc.dir,
      }))
      worker.postMessage({ type: 'update', documents: docData })
    },
    search(query: string, loc: string) {
      const worker = getSearchWorker()
      const id = ++searchId
      searchStore = this  // Store reference for worker callback

      // Update query immediately so watchers know we're handling this
      this.query = query

      // Clear old results immediately - don't show stale data
      this.searchResults = []

      if (!query) {
        this.searchLoading = false
        return
      }

      this.searchLoading = true
      worker.postMessage({ type: 'search', query, loc, id })
    },
    login(username: string, privileged: boolean) {
      this.user.username = username
      this.user.privileged = privileged
      this.user.isLoggedIn = true
      this.dialog = ''
      if (!this.connected) resumeWatching()
    },
    clearSensitiveData() {
      // Clear all sensitive state on logout or auth failure
      localStorage.removeItem('cista-files')
      this.document = []
      this.selected.clear()
      this.user.username = ''
      this.user.privileged = false
      this.user.isLoggedIn = false
      this.connected = false
      this.dialog = ''
      this.cursor = ''
    },
    async logout() {
      console.log("Logout")
      try {
        const res = await fetch('/auth/api/logout', { method: 'POST' })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          this.error = data.message || data.detail || 'Logout failed'
          return
        }
      } catch (e) {
        this.error = 'Logout failed'
        return
      }
      this.clearSensitiveData()
      resumeWatching()
    },
    toggleSort(name: SortOrder) {
      if (this.query) this.prefs.sortFiltered = this.prefs.sortFiltered === name ? '' : name
      else this.prefs.sortListing = this.prefs.sortListing === name ? '' : name
    },
    sort(name: SortOrder | '') {
      if (this.query) this.prefs.sortFiltered = name
      else this.prefs.sortListing = name
    },
    focusBreadcrumb() {
      (document.querySelector('.breadcrumb') as HTMLAnchorElement).focus()
    },
    cancelDownloads() {
      location.reload()  // FIXME
    },
    cancelUploads() {
      location.reload()  // FIXME
    },
  },
  getters: {
    sortOrder(): SortOrder { return this.query ? this.prefs.sortFiltered : this.prefs.sortListing },
    isUserLogged(): boolean { return this.user.isLoggedIn },
    recentDocuments(): Doc[] { return sorted(this.document, 'modified') },
    selectedFiles(): SelectedItems {
      const selected = this.selected
      const found = new Set<FUID>()
      const ret: SelectedItems = {
        missing: new Set(),
        docs: {},
        keys: [],
        recursive: [],
      }
      for (const doc of this.document) {
        if (selected.has(doc.key)) {
          found.add(doc.key)
          ret.keys.push(doc.key)
          ret.docs[doc.key] = doc
        }
      }
      // What did we not select?
      for (const key of selected) if (!found.has(key)) ret.missing.add(key)
      // Build a flat list including contents recursively
      const relnames = new Set<string>()
      function add(rel: string, full: string, doc: Doc) {
        if (!doc.dir && relnames.has(rel)) throw Error(`Multiple selections conflict for: ${rel}`)
        relnames.add(rel)
        ret.recursive.push([rel, full, doc])
      }
      for (const key of ret.keys) {
        const base = ret.docs[key]!
        const basepath = base.loc ? `${base.loc}/${base.name}` : base.name
        const nremove = base.loc.length
        add(base.name, basepath, base)
        for (const doc of this.document) {
          if (doc.loc === basepath || doc.loc.startsWith(basepath) && doc.loc[basepath.length] === '/') {
            const full = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
            const rel = full.slice(nremove)
            add(rel, full, doc)
          }
        }
      }
      // Sort by rel (name stored as on download)
      ret.recursive.sort((a, b) => collator.compare(a[0], b[0]))

      return ret
    }
  }
})
