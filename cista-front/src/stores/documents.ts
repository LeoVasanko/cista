import type {
  Document,
  DirEntry,
  FileEntry,
  FUID,
  SelectedItems
} from '@/repositories/Document'
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
    search: "" as string,
    selected: new Set<FUID>(),
    uploadingDocuments: [],
    uploadCount: 0 as number,
    fileExplorer: null,
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
  persist: {
    storage: sessionStorage,
    paths: ['document'],
  },
  actions: {
    updateRoot(root: DirEntry | null = null) {
      if (!root) {
        this.document = []
        return
      }
      // Transform tree data to flat documents array
      let loc = ""
      const mapper = ([name, attr]: [string, FileEntry | DirEntry]) => ({
        ...attr,
        loc,
        name,
        sizedisp: formatSize(attr.size),
        modified: formatUnixDate(attr.mtime),
        haystack: haystackFormat(name),
      })
      const queue = [...Object.entries(root.dir ?? {}).map(mapper)]
      const docs = []
      for (let doc; (doc = queue.shift()) !== undefined;) {
        docs.push(doc)
        if ("dir" in doc) {
          // Recurse but replace recursive structure with boolean
          loc = doc.loc ? `${doc.loc}/${doc.name}` : doc.name
          queue.push(...Object.entries(doc.dir).map(mapper))
          // @ts-ignore
          doc.dir = true
        }
        // @ts-ignore
        else doc.dir = false
      }
      // Pre sort directory entries folders first then files, names in natural ordering
      docs.sort((a, b) =>
        // @ts-ignore
        b.dir - a.dir ||
        collator.compare(a.name, b.name)
      )
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
