<template>
  <ModalDialog name=settings2 title="Settings">
    <form>
      <template v-if="store.user.isLoggedIn">
        <h3>Update your authentication</h3>
        <div class="login-container">
          <label for="username">New password:</label>
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
        <h3 class="error-text">
          {{ form.error || '\u00A0' }}
        </h3>
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
  password: '',
  error: ''
})

const close = () => {
  form.passwordChange = ''
  form.password = ''
  form.error = ''
  store.dialog = ''
}
const submit = async (ev: Event) => {
  ev.preventDefault()
  try {
    form.error = ''
    if (form.passwordChange) {
      if (!form.password) {
        form.error = '⚠️ Current password is required'
        password.value!.focus()
        return
      }
      await changePassword(store.user.username, form.passwordChange, form.password)
    }
    close()
  } catch (error) {
    const httpError = error as ISimpleError
    form.error = httpError.message || '🛑 Unknown error'
  } finally {
    confirmLoading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr 2fr;
  justify-content: center;
  align-items: center;
  margin: 1rem 0;
}
.dialog-buttons {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.button-login {
  color: #fff;
  background: var(--soft-color);
  cursor: pointer;
  font-weight: bold;
  border: 0;
  border-radius: .5rem;
  padding: .5rem 2rem;
  margin-left: auto;
  transition: all var(--transition-time) linear;
}
.button-login:hover, .button-login:focus {
  background: var(--accent-color);
  box-shadow: 0 0 .3rem #000;
}
.error-text {
  color: var(--red-color);
  height: 1em;
}
</style>
