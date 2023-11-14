import { Doc } from '@/repositories/Document'
import { collator } from '@/utils'

export const ordering = {
  name: (a: Doc, b: Doc) => collator.compare(a.name, b.name),
  modified: (a: Doc, b: Doc) => b.mtime - a.mtime,
  size: (a: Doc, b: Doc) => b.size - a.size
}
export type SortOrder = keyof typeof ordering | ''
export const sorted = (documents: Doc[], order: SortOrder) => {
  if (!order) return documents
  const sorted = [...documents]
  sorted.sort(ordering[order])
  return sorted
}
