<template>
  <ModalDialog name=usermgmt title="Admin Settings">
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else>
      <h3>Server Settings</h3>
      <div class="form-row">
        <label for="authMode">Authentication:</label>
        <select
          id="authMode"
          v-model="serverSettings.authentication"
          @change="updateServerSettings"
        >
          <option value="password">Password (built-in users)</option>
          <option value="paskia">Paskia (external SSO)</option>
          <option value="none">None (public access)</option>
        </select>
      </div>
      <template v-if="serverSettings.authentication === 'password'">
      <h3>Users</h3>
      <button @click="addUser" class="button" title="Add new user">➕ Add User</button>
      <div v-if="success" class="success-message" @click="copySuccess(false)">
        {{ success }}
        <button v-if="success.includes('Password:') || success.includes('New password:')" @click.stop="copySuccess(true)" class="button small" title="Copy to clipboard">{{ copyButtonText }}</button>
      </div>
      <table>
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
      </template>
      <p class="error-text">{{ error || '\u00A0' }}</p>
      <div class="dialog-buttons">
        <button @click="close" class="button">Close</button>
      </div>
    </div>
  </ModalDialog>
</template>

<script lang="ts" setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { listUsers, createUser, updateUser, deleteUser, updateAuthentication, type AuthMode } from '@/repositories/User'
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
const copyButtonText = ref('📋')
const serverSettings = reactive({
  authentication: 'password' as AuthMode
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

const copySuccess = async (isButtonClick: boolean = false) => {
  const passwordMatch = success.value.match(/(?:Password|New password): (.+)/)
  if (passwordMatch) {
    await navigator.clipboard.writeText(passwordMatch[1]!)
    if (isButtonClick) {
      // Show "Copied!" indication on button
      copyButtonText.value = '✅ Copied!'
      // Hide password and button immediately after copying
      const baseMessage = success.value.replace(/(?:Password|New password): .+/, 'Password copied to clipboard!')
      success.value = baseMessage
      // Hide the entire message after 3 seconds
      setTimeout(() => {
        success.value = ''
        copyButtonText.value = '📋'
      }, 3000)
    } else {
      // Just hide the message when clicking elsewhere
      success.value = ''
    }
  }
}

const updateServerSettings = async () => {
  try {
    error.value = ''
    success.value = ''
    await updateAuthentication(serverSettings.authentication)
    // Update store
    store.server.authentication = serverSettings.authentication
    success.value = 'Server settings updated'
  } catch (e) {
    const httpError = e as ISimpleError
    error.value = httpError.message || 'Failed to update settings'
  }
}

onMounted(() => {
  serverSettings.authentication = store.server.authentication || 'password'
  loadUsers()
})

watch(() => store.server.authentication, (newVal) => {
  serverSettings.authentication = newVal || 'password'
})
</script>

<style scoped>
/* Component-specific styles - most styling comes from ModalDialog.vue global styles */
</style>
