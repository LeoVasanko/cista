<template>
  <div class="text-editor">
    <div class="editor-body">
      <div v-if="loading" class="status">Loading…</div>
      <div v-else-if="error" class="status error">{{ error }}</div>
      <textarea
        v-else
        ref="textarea"
        v-model="content"
        spellcheck="false"
        @keydown="onKeydown"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { apiFetch } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'

const route = useRoute()
const store = useMainStore()

const MAX_SIZE = 1024 * 1024 // 1 MiB

const filePath = computed(() => decodeURIComponent(route.path.slice(6))) // strip /edit/
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
const textarea = ref<HTMLTextAreaElement | null>(null)

const dirty = computed(() => content.value !== original.value)

onBeforeRouteLeave((_to, _from, next) => {
  if (!dirty.value) {
    next()
    return
  }
  const discard = window.confirm('You have unsaved changes. Discard them?')
  next(discard)
})

const beforeUnload = (event: BeforeUnloadEvent) => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

const onKeydown = (ev: KeyboardEvent) => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') {
    ev.preventDefault()
    save()
  }
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
  store.editorSave = save
  window.addEventListener('beforeunload', beforeUnload)
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
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load file'
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (store.editorSave === save) {
    store.editorSave = null
  }
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<style scoped>
.text-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1a1a1a;
  color: #ddd;
}
.editor-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.editor-body textarea {
  flex: 1;
  width: 100%;
  resize: none;
  border: none;
  outline: none;
  padding: 1rem;
  font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 0.875rem;
  line-height: 1.5;
  background: #1a1a1a;
  color: #ddd;
  white-space: pre;
  overflow-wrap: normal;
  overflow-x: auto;
}
.editor-body textarea::selection {
  background: var(--accent-color, #007bff);
  color: #000;
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
