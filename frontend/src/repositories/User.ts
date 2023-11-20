import Client from '@/repositories/Client'
import { useMainStore } from '@/stores/main'
export const url_login = '/login'
export const url_logout = '/logout'
export const url_password = '/password-change'

export async function loginUser(username: string, password: string) {
  const user = await Client.post(url_login, {
    username,
    password
  })
  return user
}
export async function logoutUser() {
  const data = await Client.post(url_logout)
  return data
}

export async function changePassword(username: string, passwordChange: string, password: string) {
  const data = await Client.post(url_password, {
    username,
    passwordChange,
    password
  })
  return data
}
