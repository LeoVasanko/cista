// Search worker - runs search in background thread
// Receives document updates and search queries, returns incremental results

interface DocData {
  loc: string
  name: string
  key: string
  size: number
  allocated: number
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
let recentDocuments: WorkerDoc[] = []  // Sorted by mtime descending
let currentSearchId = 0

// Search result cache - cleared when documents change
interface CacheEntry {
  query: string         // Normalized query string
  results: WorkerDoc[]  // Matched results (up to limit)
  complete: boolean     // True if search scanned all documents
}
const searchCache: CacheEntry[] = []
const MAX_CACHE_SIZE = 10
const RESULT_LIMIT = 100

// Normalize string for search (remove diacritics, lowercase)
// Haystack adds ^ and $ markers to allow matching start/end of name
function normalizeHaystack(str: string): string {
  return '^' + str.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase() + '$'
}

function normalizeQuery(str: string): string {
  return str.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

// Test if document matches search query
function matches(haystack: string, query: string, words: string[]): boolean {
  return haystack.includes(query) || words.every(word => haystack.includes(word))
}

// Collator for sorting
const collator = new Intl.Collator('en', { sensitivity: 'base', numeric: true })

// Yield control to allow new messages to be processed
const yieldControl = (): Promise<void> => new Promise(resolve => setTimeout(resolve, 0))

// Find best cache entry to filter from
// Returns entry if new query's results are guaranteed to be a subset of cached results
// Only valid if the cached search was complete (scanned all documents)
function findCacheSubset(query: string): CacheEntry | null {
  // Look for a cached query that the new query starts with
  // e.g., cached "foo" can be used for "foobar" or "foo bar"
  // The longer the prefix, the better (fewer items to filter)
  // IMPORTANT: Only use complete cache entries - incomplete ones may have
  // missed results that would match the more specific query
  let best: CacheEntry | null = null
  for (const entry of searchCache) {
    if (entry.complete && query.startsWith(entry.query)) {
      if (!best || entry.query.length > best.query.length) {
        best = entry
      }
    }
  }
  return best
}

// Add result to cache
function addToCache(query: string, results: WorkerDoc[], complete: boolean) {
  // Remove existing entry for same query if any
  const idx = searchCache.findIndex(e => e.query === query)
  if (idx !== -1) searchCache.splice(idx, 1)
  // Add to front (most recent)
  searchCache.unshift({ query, results, complete })
  // Trim cache
  if (searchCache.length > MAX_CACHE_SIZE) searchCache.pop()
}

// Clear cache (called when documents change)
function clearCache() {
  searchCache.length = 0
}

// Perform search with incremental results
async function performSearch(rawQuery: string, loc: string, searchId: number) {
  const query = normalizeQuery(rawQuery)
  const words = query.split(/\s+/)
  const results: WorkerDoc[] = []
  let lastResultCount = 0

  // Check cache for exact match
  const exactMatch = searchCache.find(e => e.query === query)
  if (exactMatch) {
    if (currentSearchId === searchId) {
      postResults(exactMatch.results, rawQuery, loc, searchId, true)
    }
    return
  }

  // Check if we can filter from a cached superset
  const cacheEntry = findCacheSubset(query)
  if (cacheEntry) {
    // Fast path: filter from cached results (only used for complete cache entries)
    for (const doc of cacheEntry.results) {
      if (matches(doc.haystack, query, words)) {
        results.push(doc)
      }
    }
    // Cache entry was complete, so filtered results are also complete
    addToCache(query, results, true)

    if (currentSearchId === searchId) {
      postResults(results, rawQuery, loc, searchId, true)
    }
    return
  }

  // Slow path: scan all documents
  const batchSize = 500
  for (let i = 0; i < recentDocuments.length && results.length < RESULT_LIMIT; i += batchSize) {
    if (currentSearchId !== searchId) return  // Superseded

    // Process batch
    const end = Math.min(i + batchSize, recentDocuments.length)
    for (let j = i; j < end && results.length < RESULT_LIMIT; j++) {
      const doc = recentDocuments[j]!
      if (matches(doc.haystack, query, words)) {
        results.push(doc)
      }
    }

    // Post incremental results if we found new matches
    if (results.length > lastResultCount && currentSearchId === searchId) {
      lastResultCount = results.length
      postResults(results, rawQuery, loc, searchId, false)
    }

    // Yield control between batches
    if (i + batchSize < recentDocuments.length && results.length < RESULT_LIMIT) {
      await yieldControl()
    }
  }

  // Cache and post final results
  addToCache(query, results, results.length < RESULT_LIMIT)
  if (currentSearchId === searchId) {
    postResults(results, rawQuery, loc, searchId, true)
  }
}

// Post results to main thread
function postResults(docs: WorkerDoc[], query: string, loc: string, id: number, done: boolean) {
  const sorted = sortResults(docs, query, loc)
  postMessage({
    type: 'results',
    docs: sorted.map(({ haystack, ...rest }) => rest),
    id,
    done
  } as ResultMessage)
}

// Sort results by relevance
function sortResults(docs: WorkerDoc[], query: string, loc: string): WorkerDoc[] {
  const locsub = loc + '/'
  return [...docs].sort((a, b) => (
    // Current folder first
    Number(b.loc === loc) - Number(a.loc === loc) ||
    // Then subfolders
    Number(b.loc.startsWith(locsub)) - Number(a.loc.startsWith(locsub)) ||
    // Then by location
    collator.compare(a.loc, b.loc) ||
    // Folders before files
    Number(b.dir) - Number(a.dir) ||
    // Exact name match first
    Number(b.name.includes(query)) - Number(a.name.includes(query)) ||
    // Finally by name
    collator.compare(a.name, b.name)
  ))
}

// Handle incoming messages
self.onmessage = async (e: MessageEvent<IncomingMessage>) => {
  const msg = e.data

  if (msg.type === 'update') {
    // Update document list with haystacks, sorted by mtime descending
    recentDocuments = msg.documents
      .map(doc => ({ ...doc, haystack: normalizeHaystack(doc.name) }))
      .sort((a, b) => b.mtime - a.mtime)
    clearCache()
  } else if (msg.type === 'search') {
    currentSearchId = msg.id
    if (msg.query) {
      await performSearch(msg.query, msg.loc, msg.id)
    } else {
      // Empty query - no results needed
      postMessage({ type: 'results', docs: [], id: msg.id, done: true } as ResultMessage)
    }
  }
}
