import { formatSize, formatUnixDate } from "@/utils"

export type FUID = string

export type DocProps = {
  loc: string
  name: string
  key: FUID
  size: number
  allocated: number
  mtime: number
  dir: boolean
  ghost?: boolean
  expires?: number  // Unix timestamp for ghost expiry
}

export class Doc {
  public loc: string = ""
  public key: FUID = ""
  public size: number = 0
  public allocated: number = 0
  public mtime: number = 0
  public dir: boolean = false
  public ghost: boolean = false
  public expires: number = 0  // Unix timestamp for ghost expiry (0 = no expiry)
  /** @internal Use the name getter/setter instead */
  public _name: string = ""

  constructor(props: Partial<DocProps> = {}) {
    const { name, ...rest } = props
    Object.assign(this, rest)
    if (name) this._name = name  // Skip validation/haystack for bulk loading
  }
  get name() { return this._name }
  set name(name: string) {
    if (name.includes('/') || name.startsWith('.')) throw Error(`Invalid name: ${name}`)
    this._name = name
  }
  get sizedisp(): string { return formatSize(this.size) }
  /** Returns a sparse allocation indicator symbol, or empty string if fully allocated */
  get sparseIndicator(): string {
    if (this.dir || this.size <= this.allocated) return ''
    if (this.allocated === 0) return '⭕'  // exactly zero
    const ratio = this.allocated / this.size
    // Round to nearest 25%: ◔◑◕⬤
    const rounded = Math.round(ratio * 4)  // 0,1,2,3,4
    return ['◔', '◔', '◑', '◕', '⬤'][rounded]!  // 0 maps to ◔ since we handled exact 0 above
  }
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
  get complete(): boolean {
    return !this.ghost && (this.dir || this.size <= this.allocated)
  }
  get previewable(): boolean {
    // Folders cannot be previewable
    if (this.dir) return false
    if (this.img) return true
    // Not a comprehensive list, but good enough for now
    return ['mp4', 'mkv', 'webm', 'ogg', 'mp3', 'flac', 'aac', 'pdf'].includes(this.ext)
  }
  get previewurl(): string {
    if (!this.complete || !this.previewable) return ''
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
  number,  // mtime
  number,  // size
  number,  // allocated (actual disk usage)
  number,  // isfile
]

export type UpdateEntry = ['k', number] | ['d', number] | ['i', Array<FileEntry>]

// Helper structure for selections
export interface SelectedItems {
  keys: FUID[]
  docs: Record<FUID, Doc>
  recursive: Array<[string, string, Doc]>
  missing: Set<FUID>
}
