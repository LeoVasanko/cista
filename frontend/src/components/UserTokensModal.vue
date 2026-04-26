<template>
  <ModalDialog name=tokens title="My API Tokens">
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else>
      <p class="hint">Create tokens to access Cista from scripts or other apps. Tokens are tied to your account.</p>

      <!-- Creation form -->
      <div v-if="mode === 'creating'" class="create-form">
        <label for="token-name">Token name (optional)</label>
        <input
          id="token-name"
          v-model="newTokenName"
          type="text"
          placeholder="e.g. backup-script"
          @keyup.enter="submitCreate"
          ref="nameInput"
        />
        <div class="form-actions">
          <button @click="submitCreate" class="button primary" :disabled="creating">Create</button>
          <button @click="cancelCreate" class="button">Cancel</button>
        </div>
      </div>

      <!-- Creation result -->
      <div v-else-if="mode === 'created' && createdToken" class="created-result">
        <p class="success-title">✅ Token created</p>
        <p class="hint">Copy this URL — it will not be shown again.</p>
        <div class="url-box">
          <code class="token-url">{{ createdToken.url }}</code>
          <button @click="copyUrl" class="button small">{{ copyButtonText }}</button>
        </div>
        <p class="hint">Use it like: <code>curl {{ createdToken.url }}/...</code></p>
        <div class="form-actions">
          <button @click="finishCreate" class="button primary">Done</button>
        </div>
      </div>

      <!-- Token list -->
      <div v-else>
        <button @click="startCreate" class="button" title="Add new token">➕ Add Token</button>
        <table v-if="tokens.length">
          <thead>
            <tr>
              <th>Name</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="token in tokens" :key="token.id">
              <td>{{ token.name || 'Unnamed' }}</td>
              <td>{{ formatDate(token.created) }}</td>
              <td>
                <button @click="deleteTokenAction(token.id)" class="button small danger" title="Revoke token">🗑️</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">You have no API tokens.</p>
      </div>

      <div class="dialog-buttons">
        <button @click="close" class="button">Close</button>
      </div>
    </div>
  </ModalDialog>
</template>

<script lang="ts" setup>
import { ref, watch, nextTick } from 'vue'
import { listTokens, createToken, deleteToken } from '@/repositories/User'
import type { ISimpleError } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'

interface Token {
  id: string
  username: string
  sso_user_id: string
  name: string
  created: number
}

interface CreatedToken extends Token {
  key: string
  url: string
}

const store = useMainStore()
const loading = ref(true)
const tokens = ref<Token[]>([])
const mode = ref<'list' | 'creating' | 'created'>('list')
const newTokenName = ref('')
const creating = ref(false)
const createdToken = ref<CreatedToken | null>(null)
const copyButtonText = ref('📋')
const nameInput = ref<HTMLInputElement | null>(null)

const close = () => {
  store.dialog = ''
  resetCreate()
}

const resetCreate = () => {
  mode.value = 'list'
  newTokenName.value = ''
  creating.value = false
  createdToken.value = null
  copyButtonText.value = '📋'
}

const loadTokens = async () => {
  try {
    loading.value = true
    const data = await listTokens()
    tokens.value = data.tokens
  } catch (e) {
    const httpError = e as ISimpleError
    store.showToast(httpError.message || 'Failed to load tokens')
  } finally {
    loading.value = false
  }
}

const startCreate = () => {
  mode.value = 'creating'
  nextTick(() => nameInput.value?.focus())
}

const cancelCreate = () => {
  resetCreate()
}

const ensureFilesBaseUrl = (url: string) => {
  const trimmed = url.replace(/\/+$/, '')
  if (trimmed.endsWith('/files')) return trimmed
  return `${trimmed}/files`
}

const submitCreate = async () => {
  if (creating.value) return
  creating.value = true
  try {
    const result = await createToken(newTokenName.value)
    await loadTokens()
    if (result.url) {
      createdToken.value = {
        ...(result as CreatedToken),
        url: ensureFilesBaseUrl((result as CreatedToken).url),
      }
      mode.value = 'created'
    }
  } catch (e) {
    const httpError = e as ISimpleError
    store.showToast(httpError.message || 'Failed to create token')
    mode.value = 'list'
  } finally {
    creating.value = false
  }
}

const finishCreate = () => {
  resetCreate()
}

const copyUrl = async () => {
  if (!createdToken.value) return
  await navigator.clipboard.writeText(createdToken.value.url)
  copyButtonText.value = '✅ Copied!'
  setTimeout(() => {
    copyButtonText.value = '📋'
  }, 2000)
}

const deleteTokenAction = async (tokenId: string) => {
  if (!confirm('Revoke this token? It will no longer work.')) return
  try {
    await deleteToken(tokenId)
    await loadTokens()
  } catch (e) {
    const httpError = e as ISimpleError
    store.showToast(httpError.message || 'Failed to revoke token')
  }
}

const formatDate = (ts: number) => {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
}

// Load tokens when dialog opens
watch(() => store.dialog, (newVal) => {
  if (newVal === 'tokens') {
    resetCreate()
    loadTokens()
  }
})
</script>

<style scoped>
.hint {
  color: #666;
  font-size: 0.875rem;
  margin-bottom: 1rem;
}
.empty {
  color: #888;
  font-style: italic;
  margin: 1rem 0;
}
.create-form {
  margin-bottom: 1rem;
}
.create-form label {
  display: block;
  margin-bottom: 0.25rem;
  font-size: 0.875rem;
  color: #444;
}
.create-form input {
  width: 100%;
  padding: 0.5rem;
  font-size: 1rem;
  border: 2px solid #888;
  border-radius: 0.25rem;
  background: #fff;
  color: #000;
  margin-bottom: 0.5rem;
}
.create-form input:focus {
  outline: none;
  border-color: #f80;
}
.form-actions {
  display: flex;
  gap: 0.5rem;
}
.created-result {
  margin-bottom: 1rem;
}
.success-title {
  color: #080;
  font-weight: bold;
  margin: 0 0 0.5rem 0;
}
.url-box {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  background: #f0f0f0;
  padding: 0.75rem;
  border-radius: 0.25rem;
  margin: 0.5rem 0;
}
.token-url {
  flex: 1;
  word-break: break-all;
  font-size: 0.875rem;
  color: #222;
}
.dialog-buttons {
  margin-top: 1rem;
  text-align: right;
}
</style>
