export function determineFileType(inputString: string): 'file' | 'folder' {
  if (inputString.includes('.') && !inputString.endsWith('.')) {
    return 'file'
  } else {
    return 'folder'
  }
}

export function formatSize(size: number) {
  if (size === 0) return 'empty'
  for (const unit of [null, 'kB', 'MB', 'GB', 'TB', 'PB', 'EB']) {
    if (size < 1e4)
      return (
        size.toLocaleString().replace(',', '\u202F') + (unit ? `\u202F${unit}` : '')
      )
    size = Math.round(size / 1000)
  }
  return 'huge'
}

export function formatUnixDate(t: number) {
  const date = new Date(t * 1000)
  const now = new Date()
  const diff = date.getTime() - now.getTime()
  const adiff = Math.abs(diff)
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  if (adiff <= 5000) return 'now'
  if (adiff <= 60000) {
    return formatter.format(Math.round(diff / 1000), 'second').replace(' ago', '').replaceAll(' ', '\u202F')
  }
  if (adiff <= 3600000) {
    return formatter.format(Math.round(diff / 60000), 'minute').replace('utes', '').replace('ute', '').replaceAll(' ', '\u202F')
  }
  if (adiff <= 86400000) {
    return formatter.format(Math.round(diff / 3600000), 'hour').replaceAll(' ', '\u202F')
  }
  if (adiff <= 604800000) {
    return formatter.format(Math.round(diff / 86400000), 'day').replaceAll(' ', '\u202F')
  }
  let d = date.toLocaleDateString('en-ie', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  }).replace("Sept", "Sep")
  if (d.length === 14) d = d.replace(' ', ' \u2007')  // dom < 10 alignment (add figure space)
  d = d.replaceAll(' ', '\u202F').replace('\u202F', '\u00A0')  // nobr spaces, thin w/ date but not weekday
  d = d.slice(0, -4) + d.slice(-2)  // Two digit year is enough
  return d
}

export function getFileExtension(filename: string) {
  const dotIndex = filename.lastIndexOf('.')
  if (dotIndex === -1 || dotIndex === filename.length - 1) {
    return '' // No extension
  }
  return filename.slice(dotIndex + 1)
}
interface FileTypes {
  [key: string]: string[]
}

const filetypes: FileTypes = {
  video: ['avi', 'mkv', 'mov', 'mp4', 'webm'],
  image: ['avif', 'gif', 'jpg', 'jpeg', 'png', 'webp', 'svg'],
  pdf: ['pdf'],
}

export function getFileType(name: string): string {
  const dotIndex = name.lastIndexOf('.')
  if (dotIndex === -1 || dotIndex === name.length - 1) return 'unknown'
  const ext = name.slice(dotIndex + 1).toLowerCase()
  return Object.keys(filetypes).find(type => filetypes[type]!.includes(ext)) || 'unknown'
}

// Prebuilt for fast & consistent sorting
export const collator = new Intl.Collator('en', { sensitivity: 'base', numeric: true, usage: 'search' })

// Preformat document names for faster search
export function haystackFormat(str: string) {
  const based = str.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  return '^' + based + '$'
}


// Preformat search string for faster search
export function needleFormat(query: string) {
  const based = query.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  return {based, words: based.split(/\s+/)}
}

// Test if haystack includes needle
export function localeIncludes(haystack: string, filter: { based: string, words: string[] }) {
  const {based, words} = filter
  return haystack.includes(based) || words && words.every(word => haystack.includes(word))
}
