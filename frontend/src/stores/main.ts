import type { FUID, FileEntry, SelectedItems } from '@/repositories/Document'
import { Doc } from '@/repositories/Document'
import { resumeWatching, watchConnect } from '@/repositories/WS'
import { collator } from '@/utils'
import { type SortOrder, sorted } from '@/utils/docsort'
import SearchWorker from '@/workers/searchWorker?worker'
import { type StateTree, defineStore } from 'pinia'
import { documentRef, getDocuments, setDocuments, triggerUpdate } from './documentStore'

// Singleton search worker instance
let searchWorker: Worker | null = null
let searchId = 0
let searchStore: ReturnType<typeof useMainStore> | null = null
let loadingTimer: ReturnType<typeof setTimeout> | null = null
let clearOldResultsTimer: ReturnType<typeof setTimeout> | null = null
let lastResultUpdate = 0

function getSearchWorker(): Worker {
  if (!searchWorker) {
    searchWorker = new SearchWorker()
    // Set up message handler once
    searchWorker.onmessage = e => {
      if (!searchStore || e.data.id !== searchId) return // Stale result

      // Convert plain data back to Doc instances
      const docs = e.data.docs.map((d: any) => new Doc(d))

      // Cancel the clear-old-results timer since we have new results
      if (clearOldResultsTimer) {
        clearTimeout(clearOldResultsTimer)
        clearOldResultsTimer = null
      }

      // Throttle rapid intermediate updates to reduce UI flicker
      const now = performance.now()
      if (!e.data.done && now - lastResultUpdate < 50) {
        return // Skip intermediate update if too recent
      }
      lastResultUpdate = now

      searchStore.searchResults = docs

      if (e.data.done) {
        // Clear the loading timer and hide spinner
        if (loadingTimer) {
          clearTimeout(loadingTimer)
          loadingTimer = null
        }
        searchStore.searchLoading = false
      }
    }
  }
  return searchWorker
}

// Ghost expiry time in seconds
const GHOST_TTL = 30

// Periodic cleanup interval
let cleanupInterval: ReturnType<typeof setInterval> | null = null

export const useMainStore = defineStore('main', {
  state: () => ({
    // Ghosts are temporary optimistic-update files/folders shown until server confirms
    ghosts: [] as Doc[],
    // Hidden paths for optimistic delete (path -> expiry timestamp)
    hiddenPaths: new Map<string, number>(),
    // Version counter to trigger reactivity when external document list changes
    docVersion: 0,
    selected: new Set<FUID>([]),
    query: '' as string,
    searchResults: [] as Doc[],
    searchLoading: false,
    _searchRouteTimer: null as ReturnType<typeof setTimeout> | null,
    fileExplorer: null as any,
    error: '' as string, // Permanent status message (e.g., "Reconnecting...")
    toast: '' as string, // Temporary toast (auto-dismisses)
    toastTimeout: null as ReturnType<typeof setTimeout> | null,
    connected: false,
    authInProgress: false,
    cursor: '' as string,
    server: {} as Record<string, any> & {
      public?: boolean
      paskia?: boolean
      office_previews?: boolean
    },
    dialog: '' as '' | 'settings' | 'usermgmt' | 'accessdenied' | 'tokens' | 'about',
    uprogress: {} as any,
    dprogress: {} as any,
    prefs: {
      gallery: false,
      sortListing: '' as SortOrder,
      sortFiltered: '' as SortOrder,
      searchHotkey: '/' // Character shown for search hotkey (Slash key)
    },
    user: {
      username: '' as string,
      privileged: false as boolean,
      isLoggedIn: false as boolean
    },
    transitionDirection: 'none' as 'forward' | 'backward' | 'none',
    space: {
      disk: 0,
      free: 0,
      used: 0,
      storage: 0,
      allocated: 0
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
    }
  },
  actions: {
    updateRoot(root: FileEntry[]) {
      const docs = []
      let loc = [] as string[]
      for (const [level, name, key, mtime, size, allocated, isfile, ar] of root) {
        loc = loc.slice(0, level - 1)
        docs.push(
          new Doc({
            name,
            loc: level ? loc.join('/') : '/',
            key,
            size,
            allocated,
            mtime,
            dir: !isfile,
            ar
          })
        )
        loc.push(name)
      }
      // Store in non-reactive external storage
      setDocuments(docs)
      // Clear ghosts that now exist in the real list
      const realPaths = new Set(docs.map(d => (d.loc ? `${d.loc}/${d.name}` : d.name)))
      this.ghosts = this.ghosts.filter(
        g => !realPaths.has(g.loc ? `${g.loc}/${g.name}` : g.name)
      )
      // Clear hidden paths that no longer exist (deletion confirmed)
      for (const path of this.hiddenPaths.keys()) {
        if (!realPaths.has(path)) this.hiddenPaths.delete(path)
      }
      // Start cleanup timer if not running
      this.startCleanupTimer()
      // Bump version to trigger reactive updates
      this.docVersion++
      // Sync documents to search worker
      this.syncSearchWorker()
    },
    /** Patch aspect ratios on existing docs from a server ar update message */
    updateAr(arMap: Record<string, number>) {
      const docs = getDocuments()
      let changed = false
      for (const doc of docs) {
        const ar = arMap[doc.key]
        if (ar != null && doc.ar !== ar) {
          doc.ar = ar
          changed = true
        }
      }
      if (changed) {
        triggerUpdate()
        this.docVersion++
      }
    },
    /** Add a ghost file/folder for optimistic UI updates */
    addGhost(doc: Doc) {
      doc.ghost = true
      doc.expires = Math.floor(Date.now() / 1000) + GHOST_TTL
      this.ghosts.push(doc)
    },
    /** Clear all ghosts (e.g., on navigation or refresh) */
    clearGhosts() {
      this.ghosts = []
    },
    /** Hide a document path (optimistic delete) */
    hideDoc(path: string) {
      this.hiddenPaths.set(path, Math.floor(Date.now() / 1000) + GHOST_TTL)
    },
    /** Unhide a document path (delete failed, restore visibility) */
    unhideDoc(path: string) {
      this.hiddenPaths.delete(path)
    },
    /** Start the periodic cleanup timer */
    startCleanupTimer() {
      if (cleanupInterval) return
      cleanupInterval = setInterval(() => this.cleanupExpired(), 5000)
    },
    /** Stop the cleanup timer */
    stopCleanupTimer() {
      if (cleanupInterval) {
        clearInterval(cleanupInterval)
        cleanupInterval = null
      }
    },
    /** Remove expired ghosts and hidden paths */
    cleanupExpired() {
      const now = Math.floor(Date.now() / 1000)
      const ghostsBefore = this.ghosts.length
      const hiddenBefore = this.hiddenPaths.size
      this.ghosts = this.ghosts.filter(g => g.expires > now)
      for (const [path, expires] of this.hiddenPaths) {
        if (expires <= now) this.hiddenPaths.delete(path)
      }
      // Stop timer if nothing to clean up
      if (this.ghosts.length === 0 && this.hiddenPaths.size === 0) {
        this.stopCleanupTimer()
      }
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
      const docs = getDocuments()
      const docData = docs.map(doc => ({
        loc: doc.loc,
        name: doc.name,
        key: doc.key,
        size: doc.size,
        allocated: doc.allocated,
        mtime: doc.mtime,
        dir: doc.dir
      }))
      worker.postMessage({ type: 'update', documents: docData })
    },
    /** Notify UI/search that existing document objects were mutated in-place */
    documentsChanged() {
      triggerUpdate()
      this.docVersion++
      this.syncSearchWorker()
    },
    search(query: string, loc: string) {
      const worker = getSearchWorker()
      const id = ++searchId
      searchStore = this // Store reference for worker callback

      // Update query immediately so watchers know we're handling this
      this.query = query

      // Cancel pending timers
      if (loadingTimer) {
        clearTimeout(loadingTimer)
        loadingTimer = null
      }
      if (clearOldResultsTimer) {
        clearTimeout(clearOldResultsTimer)
        clearOldResultsTimer = null
      }

      if (!query) {
        // Clear results only when search is closed
        this.searchResults = []
        this.searchLoading = false
        return
      }

      // Keep old results briefly to avoid flicker on fast cached searches
      // But clear them after 50ms if no new results have arrived
      clearOldResultsTimer = setTimeout(() => {
        if (searchId === id) {
          this.searchResults = []
        }
        clearOldResultsTimer = null
      }, 50)

      // Delay showing loading indicator to avoid flicker on fast searches
      loadingTimer = setTimeout(() => {
        if (searchId === id) {
          // Still the current search
          this.searchLoading = true
        }
        loadingTimer = null
      }, 100)

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
      setDocuments([])
      this.ghosts = []
      this.hiddenPaths.clear()
      this.stopCleanupTimer()
      this.docVersion++
      this.selected.clear()
      this.user.username = ''
      this.user.privileged = false
      this.user.isLoggedIn = false
      this.connected = false
      this.dialog = ''
      this.cursor = ''
    },
    async logout() {
      console.log('Logout')
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
      const current = this.query ? this.prefs.sortFiltered : this.prefs.sortListing
      const newOrder = current === name ? '' : name
      if (this.query) this.prefs.sortFiltered = newOrder
      else this.prefs.sortListing = newOrder
      this.showSortToast(newOrder)
    },
    sort(name: SortOrder | '') {
      if (this.query) this.prefs.sortFiltered = name
      else this.prefs.sortListing = name
      this.showSortToast(name)
    },
    showSortToast(order: SortOrder | '') {
      const labels: Record<string, string> = {
        '': 'Folders first',
        name: 'Alphabetical order',
        modified: 'Newest first',
        size: 'Largest first'
      }
      this.showToast(labels[order] || order, 1200)
    },
    focusBreadcrumb() {
      ;(document.querySelector('.breadcrumb') as HTMLAnchorElement).focus()
    },
    cancelDownloads() {
      location.reload() // FIXME
    },
    cancelUploads() {
      location.reload() // FIXME
    }
  },
  getters: {
    sortOrder(): SortOrder {
      return this.query ? this.prefs.sortFiltered : this.prefs.sortListing
    },
    isUserLogged(): boolean {
      return this.user.isLoggedIn
    },
    /** Get documents count (triggers on docVersion change) */
    documentCount(): number {
      // Access docVersion to make this reactive
      void this.docVersion
      return getDocuments().length
    },
    recentDocuments(): Doc[] {
      // Access docVersion to make this reactive
      void this.docVersion
      return sorted(getDocuments(), 'modified')
    },
    selectedFiles(): SelectedItems {
      // Access docVersion to make this reactive
      void this.docVersion
      const docs = getDocuments()
      const selected = this.selected
      const found = new Set<FUID>()
      const ret: SelectedItems = {
        missing: new Set(),
        docs: {},
        keys: [],
        recursive: []
      }
      for (const doc of docs) {
        if (selected.has(doc.key)) {
          found.add(doc.key)
          ret.keys.push(doc.key)
          ret.docs[doc.key] = doc
        }
      }
      // What did we not select?
      for (const key of selected) if (!found.has(key)) ret.missing.add(key)
      // Build a flat list including contents recursively
      for (const key of ret.keys) {
        const base = ret.docs[key]!
        const basepath = base.loc ? `${base.loc}/${base.name}` : base.name
        const nremove = base.loc.length
        ret.recursive.push([base.name, basepath, base])
        for (const doc of docs) {
          if (
            doc.loc === basepath ||
            (doc.loc.startsWith(basepath) && doc.loc[basepath.length] === '/')
          ) {
            const full = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
            const rel = full.slice(nremove)
            ret.recursive.push([rel, full, doc])
          }
        }
      }
      // Sort by rel (name stored as on download)
      ret.recursive.sort((a, b) => collator.compare(a[0], b[0]))

      return ret
    }
  }
})
