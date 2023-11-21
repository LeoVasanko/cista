import { useMainStore } from '@/stores/main'

const store = useMainStore()

export const exists = (path: string[]) => store.document.some(doc => (doc.loc ? `${doc.loc}/${doc.name}` : doc.name) === path.join('/'))
