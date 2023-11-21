import { useMainStore } from '@/stores/main'


export const exists = (path: string[]) => {
  const store = useMainStore()
  const p = path.join('/')
  return store.document.some(doc => (doc.loc ? `${doc.loc}/${doc.name}` : doc.name) === p)
}
