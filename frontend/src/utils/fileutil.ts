import { useMainStore } from '@/stores/main'
import { getDocuments } from '@/stores/documentStore'


export const exists = (path: string[]) => {
  const store = useMainStore()
  // Access docVersion to make this reactive
  void store.docVersion
  const p = path.join('/')
  return getDocuments().some(doc => (doc.loc ? `${doc.loc}/${doc.name}` : doc.name) === p)
}

/** Strip file extension intelligently (handles .tar.gz, name.with.dots.pdf, etc.) */
export const stripExt = (name: string): string => {
  // Common compound extensions
  const compoundExts = ['.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst']
  const lower = name.toLowerCase()
  for (const ext of compoundExts) {
    if (lower.endsWith(ext)) return name.slice(0, -ext.length)
  }
  // Regular extension: only strip if the extension looks like one (2-5 chars, alphanumeric)
  const lastDot = name.lastIndexOf('.')
  if (lastDot > 0) {
    const ext = name.slice(lastDot + 1)
    if (ext.length >= 2 && ext.length <= 5 && /^[a-zA-Z0-9]+$/.test(ext)) {
      return name.slice(0, lastDot)
    }
  }
  return name
}

/** Generate a sensible zip filename for a selection of items */
export const zipName = (items: { name: string; loc: string }[]): string => {
  const names = items.map(d => d.name)
  if (names.length === 1) {
    // Single item - use its name
    return stripExt(names[0]!)
  }
  // Check if all items share the same direct parent folder
  const locs = items.map(d => d.loc)
  const sameLoc = locs.every(loc => loc === locs[0])
  if (sameLoc && locs[0]) {
    // All items in same folder - use folder name
    return locs[0].split('/').pop()!
  }
  if (names.length <= 3) {
    // Few items from different folders - join basenames with dot
    return names.map(stripExt).join('.')
  }
  // Many items from different folders - first basename + indicator
  return `${stripExt(names[0]!)}.etc`
}
