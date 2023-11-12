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

export type FileEntry = [
  number,  // level
  string,  // name
  FUID,
  number, //mtime
  number, // size
  number, // isfile
]

export type UpdateEntry = ['k', number] | ['d', number] | ['i', Array<FileEntry>]

// Helper structure for selections
export interface SelectedItems {
  keys: FUID[]
  docs: Record<FUID, Document>
  recursive: Array<[string, string, Document]>
  missing: Set<FUID>
}
