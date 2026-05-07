<template>
  <div class="text-editor">
    <div class="editor-body">
      <div v-if="loading" class="status">Loading…</div>
      <div v-else-if="error" class="status error">{{ error }}</div>
      <div v-else ref="editorHost" class="editor-host"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { indentWithTab } from '@codemirror/commands'
import { LanguageDescription } from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import { Compartment, EditorState } from '@codemirror/state'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView, keymap } from '@codemirror/view'
import { basicSetup } from 'codemirror'
import { apiFetch } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'
import {
  computed,
  nextTick,
  onActivated,
  onDeactivated,
  onMounted,
  onUnmounted,
  ref
} from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const store = useMainStore()

const MAX_SIZE = 1024 * 1024 // 1 MiB

const filePath = computed(() => {
  const raw = decodeURIComponent(route.path).split('//')[0] ?? ''
  return raw.replace(/^\//, '').replace(/\/$/, '')
})
const filename = computed(() => filePath.value.split('/').pop() || '')

const filesUrl = computed(() => {
  return (
    '/files/' +
    filePath.value
      .split('/')
      .map(part => encodeURIComponent(part))
      .join('/')
  )
})

const content = ref('')
const original = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const editorHost = ref<HTMLDivElement | null>(null)
let editorView: EditorView | null = null
const languageCompartment = new Compartment()

const dirty = computed(() => content.value !== original.value)

const beforeUnload = (event: BeforeUnloadEvent) => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

let beforeUnloadActive = false

const activateEditorBindings = () => {
  store.editorSave = save
  if (!beforeUnloadActive) {
    window.addEventListener('beforeunload', beforeUnload)
    beforeUnloadActive = true
  }
}

const deactivateEditorBindings = () => {
  if (store.editorSave === save) {
    store.editorSave = null
  }
  if (beforeUnloadActive) {
    window.removeEventListener('beforeunload', beforeUnload)
    beforeUnloadActive = false
  }
}

const detectLanguage = async () => {
  const language = LanguageDescription.matchFilename(languages, filename.value)
  if (!language) return []
  try {
    return [await language.load()]
  } catch {
    return []
  }
}

const initEditor = async (text: string) => {
  if (!editorHost.value) return
  const languageExtensions = await detectLanguage()
  const state = EditorState.create({
    doc: text,
    extensions: [
      basicSetup,
      oneDark,
      languageCompartment.of(languageExtensions),
      EditorView.updateListener.of(update => {
        if (update.docChanged) {
          content.value = update.state.doc.toString()
        }
      }),
      keymap.of([
        {
          key: 'Mod-s',
          run: () => {
            void save()
            return true
          }
        },
        indentWithTab
      ])
    ]
  })
  editorView = new EditorView({ state, parent: editorHost.value })
  editorView.focus()
}

const save = async () => {
  if (saving.value || loading.value) return
  saving.value = true
  try {
    const res = await apiFetch(filesUrl.value, {
      method: 'PUT',
      body: content.value,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.message || data.detail || `${res.status} ${res.statusText}`)
    }
    original.value = content.value
    store.showToast(`Saved ${filename.value}`)
  } catch (err) {
    console.error('Save failed', err)
    store.showToast(err instanceof Error ? err.message : 'Save failed')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  activateEditorBindings()
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(filesUrl.value, { method: 'HEAD' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const size = Number(res.headers.get('content-length') || '0')
    if (size > MAX_SIZE) {
      throw new Error(
        `File is too large to edit (${(size / 1024 / 1024).toFixed(1)} MB)`
      )
    }
    const textRes = await fetch(filesUrl.value)
    if (!textRes.ok) throw new Error(`${textRes.status} ${textRes.statusText}`)
    const text = await textRes.text()
    content.value = text
    original.value = text
    loading.value = false
    await nextTick()
    await initEditor(text)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load file'
  }
  finally {
    if (loading.value) loading.value = false
  }
})

onActivated(() => {
  activateEditorBindings()
})

onDeactivated(() => {
  deactivateEditorBindings()
})

onUnmounted(() => {
  deactivateEditorBindings()
  editorView?.destroy()
  editorView = null
})
</script>

<style scoped>
.text-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1a1a1a;
  color: #ddd;
  text-align: left;
}
.editor-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.editor-host {
  flex: 1;
  min-height: 0;
}
.editor-host :deep(.cm-editor) {
  flex: 1;
  height: 100%;
  border: none;
  outline: none;
}
.editor-host :deep(.cm-scroller) {
  font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 0.875rem;
  line-height: 1.5;
  text-align: left;
}
.editor-host :deep(.cm-content) {
  padding: 1rem;
  text-align: left;
}
.editor-host :deep(.cm-selectionBackground) {
  background: var(--soft-color, #146) !important;
}
.editor-host :deep(.cm-focused .cm-selectionBackground) {
  background: var(--soft-color, #146) !important;
}
.editor-host :deep(.cm-content ::selection) {
  background: var(--soft-color, #146);
}
.editor-host :deep(.cm-content, .cm-gutter) {
  font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
}
.editor-host :deep(.cm-line, .cm-gutters, .cm-gutterElement) {
  text-align: left;
}
.status {
  padding: 2rem;
  text-align: center;
  font-size: 1rem;
  color: #888;
}
.status.error {
  color: #f55;
}
</style>
