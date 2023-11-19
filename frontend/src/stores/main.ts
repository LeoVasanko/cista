import type { FileEntry, FUID, SelectedItems } from '@/repositories/Document'
import { Doc } from '@/repositories/Document'
import { defineStore } from 'pinia'
import { collator } from '@/utils'
import { logoutUser } from '@/repositories/User'
import { watchConnect } from '@/repositories/WS'
import { shallowRef } from 'vue'
import { sorted, type SortOrder } from '@/utils/docsort'

type User = {
  username: string
  privileged: boolean
  isOpenLoginModal: boolean
  isLoggedIn: boolean
}

export const useMainStore = defineStore({
  id: 'main',
  state: () => ({
    document: shallowRef<Doc[]>([]),
    selected: new Set<FUID>(),
    query: '' as string,
    fileExplorer: null as any,
    error: '' as string,
    connected: false,
    gallery: false,
    cursor: '' as string,
    server: {} as Record<string, any>,
    prefs: {
      sortListing: '' as SortOrder,
      sortFiltered: '' as SortOrder,
    },
    user: {
      username: '',
      privileged: false,
      isLoggedIn: false,
      isOpenLoginModal: false
    } as User
  }),
  persist: {
    paths: ['prefs'],
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
    },
    login(username: string, privileged: boolean) {
      this.user.username = username
      this.user.privileged = privileged
      this.user.isLoggedIn = true
      this.user.isOpenLoginModal = false
      if (!this.connected) watchConnect()
    },
    loginDialog() {
      this.user.isOpenLoginModal = true
    },
    async logout() {
      console.log("Logout")
      await logoutUser()
      this.$reset()
      localStorage.clear()
      history.go() // Reload page
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
    }
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
        const base = ret.docs[key]
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
