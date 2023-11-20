<template>
  <ModalDialog name="login" title="Authentication required">
    <form @submit.prevent="login">
      <div class="login-container">
        <label for="username">Username:</label>
        <input
          id="username"
          name="username"
          autocomplete="username"
          spellcheck="false"
          autocorrect="off"
          required
          v-model="loginForm.username"
        />
        <label for="password">Password:</label>
        <input
          id="password"
          name="password"
          type="password"
          autocomplete="current-password"
          spellcheck="false"
          autocorrect="off"
          required
          v-model="loginForm.password"
        />
      </div>
      <h3 class="error-text">
        {{ loginForm.error || '\u00A0' }}
      </h3>
      <div class="dialog-buttons">
        <div class="spacer"></div>
        <input id="submit" type="submit" value="Login" class="button-login" />
      </div>
    </form>
  </ModalDialog>
</template>

<script lang="ts" setup>
import { reactive, ref } from 'vue'
import { loginUser } from '@/repositories/User'
import type { ISimpleError } from '@/repositories/Client'
import { useMainStore } from '@/stores/main'

const confirmLoading = ref<boolean>(false)
const store = useMainStore()

const loginForm = reactive({
  username: '',
  password: '',
  error: ''
})

const login = async () => {
  try {
    loginForm.error = ''
    confirmLoading.value = true
    const msg = await loginUser(loginForm.username, loginForm.password)
    store.login(msg.data.username, !!msg.data.privileged)
  } catch (error) {
    const httpError = error as ISimpleError
    loginForm.error = httpError.message || '🛑 Unknown error'
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
