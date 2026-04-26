import Client from '@/repositories/Client'
import { useMainStore } from '@/stores/main'
export const url_login = '/auth/login'
export const url_logout = '/auth/api/logout'
export const url_password = '/auth/password-change'

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

export async function changePassword(
  username: string,
  passwordChange: string,
  password: string
) {
  const data = await Client.post(url_password, {
    username,
    passwordChange,
    password
  })
  return data
}

export const url_users = '/auth/users'

export async function listUsers() {
  const data = await Client.get(url_users)
  return data
}

export async function createUser(
  username: string,
  password?: string,
  privileged?: boolean
) {
  const data = await Client.post(url_users, {
    username,
    password,
    privileged
  })
  return data
}

export async function updateUser(
  username: string,
  changes: { password?: string; privileged?: boolean }
) {
  const data = await Client.put(`${url_users}/${username}`, changes)
  return data
}

export async function deleteUser(username: string) {
  const data = await Client.delete(`${url_users}/${username}`)
  return data
}

export async function updatePublic(isPublic: boolean) {
  const data = await Client.put('/api/config/public', { public: isPublic })
  return data
}

export async function updateServerName(name: string) {
  const data = await Client.put('/api/config/name', { name })
  return data
}

export async function getServerConfig() {
  const data = await Client.get('/api/config')
  return data as { name: string; public: boolean }
}

export const url_tokens = '/api/tokens'

export async function listTokens() {
  const data = await Client.get(url_tokens)
  return data
}

export async function createToken(name: string) {
  const data = await Client.post(url_tokens, { name })
  return data
}

export async function deleteToken(tokenId: string) {
  const data = await Client.delete(`${url_tokens}/${tokenId}`)
  return data
}

export async function createShareToken(paths: string[], mode: 'ro' | 'rw' = 'ro') {
  const data = await Client.post('/api/share-tokens', { paths, mode })
  return data as {
    id: string
    key: string
    url: string
    mode: 'ro' | 'rw'
    paths: string[]
  }
}
