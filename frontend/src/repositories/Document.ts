import { formatSize, formatUnixDate, haystackFormat } from "@/utils"

export type FUID = string

export type DocProps = {
  loc: string
  name: string
  key: FUID
  size: number
  mtime: number
  dir: boolean
}

export class Doc {
  private _name: string = ""
  public loc: string = ""
  public key: FUID = ""
  public size: number = 0
  public mtime: number = 0
  public haystack: string = ""
  public dir: boolean = false

  constructor(props: Partial<DocProps> = {}) { Object.assign(this, props) }
  get name() { return this._name }
  set name(name: string) {
    if (name.includes('/') || name.startsWith('.')) throw Error(`Invalid name: ${name}`)
    this._name = name
    this.haystack = haystackFormat(name)
  }
  get sizedisp(): string { return formatSize(this.size) }
  get modified(): string { return formatUnixDate(this.mtime) }
  get url(): string {
    const p = this.loc ? `${this.loc}/${this.name}` : this.name
    return this.dir ? '/#/' + `${p}/`.replaceAll('#', '%23') : `/files/${p}`.replaceAll('?', '%3F').replaceAll('#', '%23')
  }
  get urlrouter(): string {
    return this.url.replace(/^\/#/, '')
  }
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
  docs: Record<FUID, Doc>
  recursive: Array<[string, string, Doc]>
  missing: Set<FUID>
}
