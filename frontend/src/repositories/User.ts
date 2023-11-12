import Client from '@/repositories/Client'
export const url_login = '/login'
export const url_logout = '/logout '

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
