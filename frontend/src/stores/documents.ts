import type { Document, FileEntry, FUID, SelectedItems } from '@/repositories/Document'
import { formatSize, formatUnixDate, haystackFormat } from '@/utils'
import { defineStore } from 'pinia'
import { collator } from '@/utils'
import { logoutUser } from '@/repositories/User'
import { watchConnect } from '@/repositories/WS'

type FileData = { id: string; mtime: number; size: number; dir: DirectoryData }
type DirectoryData = {
  [filename: string]: FileData
}
type User = {
  username: string
  privileged: boolean
  isOpenLoginModal: boolean
  isLoggedIn: boolean
}

export const useDocumentStore = defineStore({
  id: 'documents',
  state: () => ({
    document: [] as Document[],
    selected: new Set<FUID>(),
    fileExplorer: null as any,
    error: '' as string,
    connected: false,
    server: {} as Record<string, any>,
    user: {
      username: '',
      privileged: false,
      isLoggedIn: false,
      isOpenLoginModal: false
    } as User
  }),
  actions: {
    updateRoot(root: FileEntry[]) {
      const docs = []
      let loc = [] as string[]
      for (const [level, name, key, mtime, size, isfile] of root) {
        loc = loc.slice(0, level - 1)
        docs.push({
          name,
          loc: level ? loc.join('/') : '/',
          key,
          size,
          sizedisp: formatSize(size),
          mtime,
          modified: formatUnixDate(mtime),
          haystack: haystackFormat(name),
          dir: !isfile,
        })
        loc.push(name)
      }
      this.document = docs as Document[]
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
      history.go() // Reload page
    }
  },
  getters: {
    isUserLogged(): boolean {
      return this.user.isLoggedIn
    },
    recentDocuments(): Document[] {
      const ret = [...this.document]
      ret.sort((a, b) => b.mtime - a.mtime)
      return ret
    },
    largeDocuments(): Document[] {
      const ret = [...this.document]
      ret.sort((a, b) => b.size - a.size)
      return ret
    },
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
      function add(rel: string, full: string, doc: Document) {
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
