<template>
  <ModalDialog name=settings title="Settings">
    <form>
      <template v-if="store.user.isLoggedIn">
        <h3>Update your authentication</h3>
        <div class="form-grid">
          <label for="passwordChange">New password:</label>
          <input
            ref="passwordChange"
            id="passwordChange"
            type="password"
            autocomplete="new-password"
            spellcheck="false"
            autocorrect="off"
            v-model="form.passwordChange"
          />
          <label for="password">Current password:</label>
          <input
            ref="password"
            id="password"
            name="password"
            type="password"
            autocomplete="current-password"
            spellcheck="false"
            autocorrect="off"
            v-model="form.password"
          />
        </div>
        <div class="dialog-buttons">
          <input id="close" type="reset" value="Close" class="button" @click=close />
          <div class="spacer"></div>
          <input id="submit" type="submit" value="Submit" class="button" @click.prevent="submit" />
        </div>
      </template>
      <template v-else>
        <p>No settings are available because you have not logged in.</p>
        <div class="dialog-buttons">
          <div class="spacer"></div>
          <input id="close" type="reset" value="Close" class="button" @click=close />
        </div>
      </template>
    </form>
  </ModalDialog>
</template>

<script lang="ts" setup>
import { reactive, ref } from 'vue'
import { changePassword } from '@/repositories/User'
import type { ISimpleError } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'

const confirmLoading = ref<boolean>(false)
const store = useMainStore()

const passwordChange = ref()
const password = ref()

const form = reactive({
  passwordChange: '',
  password: ''
})

const close = () => {
  form.passwordChange = ''
  form.password = ''
  store.dialog = ''
}
const submit = async (ev: Event) => {
  ev.preventDefault()
  try {
    if (form.passwordChange) {
      if (!form.password) {
        store.error = '⚠️ Current password is required'
        password.value!.focus()
        return
      }
      await changePassword(store.user.username, form.passwordChange, form.password)
    }
    close()
  } catch (error) {
    const httpError = error as ISimpleError
    store.error = httpError.message || '🛑 Unknown error'
  } finally {
    confirmLoading.value = false
  }
}
</script>

<style scoped>
/* Component-specific styles - most styling comes from ModalDialog.vue global styles */
</style>
