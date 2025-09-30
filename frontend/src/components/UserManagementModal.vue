<template>
  <ModalDialog name=usermgmt title="Admin Settings">
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else>
      <h3>Server Settings</h3>
      <div class="form-row">
        <input
          id="publicServer"
          type="checkbox"
          v-model="serverSettings.public"
          @change="updateServerSettings"
        />
        <label for="publicServer">Publicly accessible without any user account.</label>
      </div>
      <h3>Users</h3>
      <button @click="addUser" class="button" title="Add new user">➕ Add User</button>
      <div v-if="success" class="success-message">
        {{ success }}
        <button @click="copySuccess" class="button small" title="Copy to clipboard">�</button>
      </div>
      <table class="user-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Admin</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.username">
            <td>{{ user.username }}</td>
            <td>
              <input
                type="checkbox"
                :checked="user.privileged"
                @change="toggleAdmin(user, $event)"
                :disabled="user.username === store.user.username"
              />
            </td>
            <td>
              <button @click="renameUser(user)" class="button small" title="Rename user">✏️</button>
              <button @click="resetPassword(user)" class="button small" title="Reset password">🔑</button>
              <button @click="deleteUserAction(user.username)" class="button small danger" :disabled="user.username === store.user.username" title="Delete user">🗑️</button>
            </td>
          </tr>
        </tbody>
      </table>
      <h3 class="error-text">{{ error || '\u00A0' }}</h3>
      <div class="dialog-buttons">
        <button @click="close" class="button">Close</button>
      </div>
    </div>
  </ModalDialog>
</template>

<script lang="ts" setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { listUsers, createUser, updateUser, deleteUser, updatePublic } from '@/repositories/User'
import type { ISimpleError } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'

interface User {
  username: string
  privileged: boolean
  lastSeen: number
}

const store = useMainStore()
const loading = ref(true)
const users = ref<User[]>([])
const error = ref('')
const success = ref('')
const serverSettings = reactive({
  public: false
})

const close = () => {
  store.dialog = ''
  error.value = ''
  success.value = ''
}

const loadUsers = async () => {
  try {
    loading.value = true
    const data = await listUsers()
    users.value = data.users
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to load users'
  } finally {
    loading.value = false
  }
}

const addUser = async () => {
  const username = window.prompt('Enter username for new user:')
  if (!username || !username.trim()) return
  try {
    error.value = ''
    success.value = ''
    const result = await createUser(username.trim(), undefined, false)
    await loadUsers()
    if (result.password) {
      success.value = `User ${username.trim()} created. Password: ${result.password}`
    }
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to add user'
  }
}

const toggleAdmin = async (user: User, event: Event) => {
  const target = event.target as HTMLInputElement
  try {
    error.value = ''
    await updateUser(user.username, { privileged: target.checked })
    user.privileged = target.checked
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to update user'
    target.checked = user.privileged // revert
  }
}

const renameUser = async (user: User) => {
  const newName = window.prompt('Enter new username:', user.username)
  if (!newName || !newName.trim() || newName.trim() === user.username) return
  // For rename, we need to create new user and delete old, or have a rename endpoint
  // Since no rename endpoint, perhaps delete and create
  try {
    error.value = ''
    success.value = ''
    const result = await createUser(newName.trim(), undefined, user.privileged)
    await deleteUser(user.username)
    await loadUsers()
    if (result.password) {
      success.value = `User renamed to ${newName.trim()}. New password: ${result.password}`
    }
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to rename user'
  }
}

const resetPassword = async (user: User) => {
  if (!confirm(`Reset password for ${user.username}? A new password will be generated.`)) return
  try {
    error.value = ''
    success.value = ''
    const result = await updateUser(user.username, { password: "" })
    if (result.password) {
      success.value = `Password reset for ${user.username}. New password: ${result.password}`
    }
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to reset password'
  }
}

const deleteUserAction = async (username: string) => {
  if (!confirm(`Delete user ${username}?`)) return
  try {
    error.value = ''
    await deleteUser(username)
    await loadUsers()
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to delete user'
  }
}

const copySuccess = async () => {
  const passwordMatch = success.value.match(/Password: (.+)/)
  if (passwordMatch) {
    await navigator.clipboard.writeText(passwordMatch[1])
    // Maybe flash or something, but for now just copy
  }
}

const updateServerSettings = async () => {
  try {
    error.value = ''
    success.value = ''
    await updatePublic(serverSettings.public)
    // Update store
    store.server.public = serverSettings.public
    success.value = 'Server settings updated'
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to update settings'
  }
}

onMounted(() => {
  serverSettings.public = store.server.public
  loadUsers()
})

watch(() => store.server.public, (newVal) => {
  serverSettings.public = newVal
})
</script>

<style scoped>
.user-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 1rem;
}
.user-table th, .user-table td {
  border: 1px solid var(--border-color);
  padding: 0.5rem;
  text-align: left;
}
.user-table th {
  background: var(--soft-color);
}
.button.small {
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  margin-right: 0.25rem;
}
.button.danger {
  background: var(--red-color);
  color: white;
}
.button.danger:hover {
  background: #d00;
}
.form-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.5rem;
}
.form-row label {
  min-width: 100px;
}
.success-message {
  background: var(--accent-color);
  color: white;
  padding: 0.5rem;
  border-radius: 0.25rem;
  margin-top: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
</style>