export type FUID = string

export type Document = {
  loc: string
  name: string
  key: FUID
  size: number
  sizedisp: string
  mtime: number
  modified: string
  haystack: string
  dir: boolean
}

export type errorEvent = {
  error: {
    code: number
    message: string
    redirect: string
  }
}

// Raw types the backend /api/watch sends us

export type FileEntry = {
  key: FUID
  size: number
  mtime: number
}

export type DirEntry = {
  key: FUID
  size: number
  mtime: number
  dir: DirList
}

export type DirList = Record<string, FileEntry | DirEntry>

export type UpdateEntry = {
  name: string
  deleted?: boolean
  key?: FUID
  size?: number
  mtime?: number
  dir?: DirList
}

// Helper structure for selections
export interface SelectedItems {
  keys: FUID[]
  docs: Record<FUID, Document>
  recursive: Array<[string, string, Document]>
  missing: Set<FUID>
}
