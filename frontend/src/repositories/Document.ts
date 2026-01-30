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
  public loc: string = ""
  public key: FUID = ""
  public size: number = 0
  public mtime: number = 0
  public haystack: string = ""
  public dir: boolean = false
  /** @internal Use the name getter/setter instead */
  public _name: string = ""

  constructor(props: Partial<DocProps> = {}) {
    const { name, ...rest } = props
    Object.assign(this, rest)
    if (name) this.name = name  // Use setter for validation
  }
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
  get img(): boolean {
    // Folders cannot be images
    if (this.dir) return false
    return ['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif', 'heic', 'heif', 'svg'].includes(this.ext)
  }
  get previewable(): boolean {
    // Folders cannot be previewable
    if (this.dir) return false
    if (this.img) return true
    // Not a comprehensive list, but good enough for now
    return ['mp4', 'mkv', 'webm', 'ogg', 'mp3', 'flac', 'aac', 'pdf'].includes(this.ext)
  }
  get previewurl(): string {
    return this.url.replace(/^\/files/, '/preview')
  }
  get ext(): string {
    const dotIndex = this.name.lastIndexOf('.')
    if (dotIndex === -1 || dotIndex === this.name.length - 1) return ''
    return this.name.slice(dotIndex + 1).toLowerCase()
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
