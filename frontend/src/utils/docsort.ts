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

/**
 * Sort documents while keeping files grouped by their folder.
 * - name: folders sorted by folder path, items within by name
 * - modified: folders sorted by newest item within results, items within by mtime
 * - size: folders sorted by largest file within results, items within by size
 */
export const sortedGrouped = (documents: Doc[], order: SortOrder) => {
  if (!order) return documents

  const compare = ordering[order]

  // Group documents by their folder location
  const byFolder = new Map<string, Doc[]>()
  for (const doc of documents) {
    const folder = doc.loc
    if (!byFolder.has(folder)) byFolder.set(folder, [])
    byFolder.get(folder)!.push(doc)
  }

  // Sort items within each folder
  for (const docs of byFolder.values()) {
    docs.sort(compare)
  }

  // Find the "best" item in each folder (first after sorting = best according to criteria)
  const folderBest = new Map<string, Doc>()
  for (const [folder, docs] of byFolder) {
    folderBest.set(folder, docs[0]!)
  }

  // Sort folders: by path for name sort, by best item for modified/size
  const sortedFolders = [...byFolder.keys()].sort((a, b) => {
    if (order === 'name') {
      return collator.compare(a, b)
    }
    return compare(folderBest.get(a)!, folderBest.get(b)!)
  })

  // Flatten back into a single array with folder grouping preserved
  const result: Doc[] = []
  for (const folder of sortedFolders) {
    result.push(...byFolder.get(folder)!)
  }

  return result
}
