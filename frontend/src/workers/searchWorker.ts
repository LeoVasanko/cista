// Search worker - runs search in background thread
// Receives document updates and search queries, returns incremental results

interface DocData {
  loc: string
  name: string
  key: string
  size: number
  mtime: number
  dir: boolean
}

interface WorkerDoc extends DocData {
  haystack: string
}

interface SearchMessage {
  type: 'search'
  query: string
  loc: string
  id: number
}

interface UpdateMessage {
  type: 'update'
  documents: DocData[]
}

type IncomingMessage = SearchMessage | UpdateMessage

interface ResultMessage {
  type: 'results'
  docs: DocData[]
  id: number
  done: boolean
}

// Worker state
let documents: WorkerDoc[] = []
let recentDocuments: WorkerDoc[] = []  // Sorted by mtime descending
let currentSearchId = 0

// Haystack formatting (same as main thread utils)
function haystackFormat(str: string): string {
  const based = str.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  return '^' + based + '$'
}

// Needle formatting
function needleFormat(query: string) {
  const based = query.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  return { based, words: based.split(/\s+/) }
}

// Test if haystack includes needle
function localeIncludes(haystack: string, filter: { based: string; words: string[] }): boolean {
  const { based, words } = filter
  return haystack.includes(based) || (words && words.every(word => haystack.includes(word)))
}

// Collator for sorting
const collator = new Intl.Collator('en', { sensitivity: 'base', numeric: true, usage: 'search' })

// Sort by mtime descending
function sortByRecent(docs: WorkerDoc[]): WorkerDoc[] {
  return [...docs].sort((a, b) => b.mtime - a.mtime)
}

// Yield control to check for new messages
function yieldControl(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0))
}

// Perform search with incremental results
async function performSearch(query: string, loc: string, searchId: number) {
  const needle = needleFormat(query)
  const limit = 100
  const batchSize = 500  // Smaller batches for faster incremental feedback
  const results: WorkerDoc[] = []
  let lastResultCount = 0

  for (let i = 0; i < recentDocuments.length && results.length < limit; i += batchSize) {
    // Check if search was superseded
    if (currentSearchId !== searchId) return

    // Process batch
    const end = Math.min(i + batchSize, recentDocuments.length)
    for (let j = i; j < end && results.length < limit; j++) {
      const doc = recentDocuments[j]!
      if (localeIncludes(doc.haystack, needle)) {
        results.push(doc)
      }
    }

    // Post incremental results if we found new matches
    if (results.length > lastResultCount && currentSearchId === searchId) {
      lastResultCount = results.length
      const sortedResults = sortResults(results, query, loc)
      postMessage({
        type: 'results',
        docs: sortedResults.map(stripHaystack),
        id: searchId,
        done: false
      } as ResultMessage)
    }

    // Yield control between batches to allow new search requests to interrupt
    if (i + batchSize < recentDocuments.length && results.length < limit) {
      await yieldControl()
    }
  }

  // Post final results
  if (currentSearchId === searchId) {
    const sortedResults = sortResults(results, query, loc)
    postMessage({
      type: 'results',
      docs: sortedResults.map(stripHaystack),
      id: searchId,
      done: true
    } as ResultMessage)
  }
}

// Sort results by relevance
function sortResults(docs: WorkerDoc[], query: string, loc: string): WorkerDoc[] {
  const locsub = loc + '/'
  return [...docs].sort((a, b) => (
    // Current folder first
    // @ts-ignore
    (b.loc === loc) - (a.loc === loc) ||
    // Then subfolders
    // @ts-ignore
    (b.loc.slice(0, locsub.length) === locsub) - (a.loc.slice(0, locsub.length) === locsub) ||
    // Then by location
    collator.compare(a.loc, b.loc) ||
    // Files after folders
    // @ts-ignore
    (a.dir === false) - (b.dir === false) ||
    // Exact name match first
    // @ts-ignore
    b.name.includes(query) - a.name.includes(query) ||
    // Finally by name
    collator.compare(a.name, b.name)
  ))
}

// Strip haystack before sending back to main thread
function stripHaystack(doc: WorkerDoc): DocData {
  const { haystack, ...rest } = doc
  return rest
}

// Handle incoming messages
self.onmessage = async (e: MessageEvent<IncomingMessage>) => {
  const msg = e.data

  if (msg.type === 'update') {
    // Update document list with haystacks
    documents = msg.documents.map(doc => ({
      ...doc,
      haystack: haystackFormat(doc.name)
    }))
    recentDocuments = sortByRecent(documents)
  } else if (msg.type === 'search') {
    currentSearchId = msg.id
    if (msg.query) {
      await performSearch(msg.query, msg.loc, msg.id)
    } else {
      // Empty query - no results needed (main thread handles folder listing)
      postMessage({
        type: 'results',
        docs: [],
        id: msg.id,
        done: true
      } as ResultMessage)
    }
  }
}
