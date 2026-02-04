// Non-reactive document storage for the full file list
// This avoids Vue reactivity overhead on large arrays

import type { Doc } from '@/repositories/Document'
import { shallowRef, triggerRef } from 'vue'

// The main document list - shallowRef means only the reference is reactive, not the contents
const documents = shallowRef<Doc[]>([])

// Version counter for manual reactivity triggering
let version = 0

export function getDocuments(): Doc[] {
  return documents.value
}

export function setDocuments(docs: Doc[]): void {
  documents.value = docs
  version++
}

export function getVersion(): number {
  return version
}

// Trigger reactivity manually (e.g., after modifications)
export function triggerUpdate(): void {
  version++
  triggerRef(documents)
}

// For computed dependencies that need to react to document changes
export const documentRef = documents
