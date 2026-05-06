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
    return formatter
      .format(Math.round(diff / 1000), 'second')
      .replace(' ago', '')
      .replaceAll(' ', '\u202F')
  }
  if (adiff <= 3600000) {
    return formatter
      .format(Math.round(diff / 60000), 'minute')
      .replace('utes', '')
      .replace('ute', '')
      .replaceAll(' ', '\u202F')
  }
  if (adiff <= 86400000) {
    return formatter
      .format(Math.round(diff / 3600000), 'hour')
      .replaceAll(' ', '\u202F')
  }
  if (adiff <= 604800000) {
    return formatter
      .format(Math.round(diff / 86400000), 'day')
      .replaceAll(' ', '\u202F')
  }
  let d = date
    .toLocaleDateString('en-ie', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
    .replace('Sept', 'Sep')
  if (d.length === 14) d = d.replace(' ', ' \u2007') // dom < 10 alignment (add figure space)
  d = d.replaceAll(' ', '\u202F').replace('\u202F', '\u00A0') // nobr spaces, thin w/ date but not weekday
  d = d.slice(0, -4) + d.slice(-2) // Two digit year is enough
  return d
}

export function getFileExtension(filename: string) {
  const dotIndex = filename.lastIndexOf('.')
  if (dotIndex === -1 || dotIndex === filename.length - 1) {
    return '' // No extension
  }
  return filename.slice(dotIndex + 1)
}
export const FILE_TYPES = {
  video: ['avi', 'mkv', 'mov', 'mp4', 'webm'],
  audio: ['mp3', 'flac', 'ogg', 'aac'],
  archive: ['zip', 'tar', 'gz', 'bz2', 'xz', '7z', 'rar'],
  document: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'rtf'],
  imageBrowser: ['avif', 'gif', 'jpg', 'jpeg', 'png', 'webp', 'svg'],
  // Images that require server-side preview (browsers cannot display them natively)
  image: ['bmp', 'heic', 'heif', 'ico', 'tif', 'tiff'],
  print: ['epub', 'mobi', 'pdf'],
  text: [
    'txt',
    'md',
    'json',
    'xml',
    'yaml',
    'yml',
    'toml',
    'ini',
    'conf',
    'config',
    'cfg',
    'log',
    'csv',
    'tsv',
    'py',
    'js',
    'ts',
    'jsx',
    'tsx',
    'html',
    'htm',
    'css',
    'scss',
    'sass',
    'less',
    'vue',
    'php',
    'rb',
    'go',
    'rs',
    'java',
    'c',
    'cpp',
    'h',
    'hpp',
    'cs',
    'swift',
    'kt',
    'sh',
    'bash',
    'zsh',
    'fish',
    'ps1',
    'bat',
    'cmd',
    'sql',
    'lua',
    'r',
    'pl',
    'dockerfile',
    'makefile',
    'gitignore',
    'gitattributes',
    'env',
    'diff',
    'patch'
  ]
} as const

export type FileCategory = keyof typeof FILE_TYPES

export function getFileType(name: string): FileCategory | 'unknown' {
  const dotIndex = name.lastIndexOf('.')
  if (dotIndex === -1 || dotIndex === name.length - 1) return 'unknown'
  const ext = name.slice(dotIndex + 1).toLowerCase()
  for (const category of Object.keys(FILE_TYPES) as FileCategory[]) {
    if ((FILE_TYPES[category] as readonly string[]).includes(ext)) {
      return category
    }
  }
  return 'unknown'
}

// Prebuilt for fast & consistent sorting
export const collator = new Intl.Collator('en', {
  sensitivity: 'base',
  numeric: true,
  usage: 'search'
})

// Preformat document names for faster search
export function haystackFormat(str: string) {
  const based = str
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
  return '^' + based + '$'
}

// Preformat search string for faster search
export function needleFormat(query: string) {
  const based = query
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
  return { based, words: based.split(/\s+/) }
}

// Test if haystack includes needle
export function localeIncludes(
  haystack: string,
  filter: { based: string; words: string[] }
) {
  const { based, words } = filter
  return (
    haystack.includes(based) || (words && words.every(word => haystack.includes(word)))
  )
}
