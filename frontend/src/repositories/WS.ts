import { useMainStore } from "@/stores/main"
import type { FileEntry, UpdateEntry, errorEvent } from "./Document"

export const controlUrl = '/api/control'
export const uploadUrl = '/api/upload'
export const watchUrl = '/api/watch'

let tree = [] as FileEntry[]
let reconnDelay = 500
let wsWatch = null as WebSocket | null

export const loadSession = () => {
  const s = localStorage['cista-files']
  if (!s) return false
  const store = useMainStore()
  try {
    tree = JSON.parse(s)
    store.updateRoot(tree)
    console.log(`Loaded session with ${tree.length} items cached`)
    return true
  } catch (error) {
    console.log("Loading session failed", error)
    return false
  }
}

const saveSession = () => {
  localStorage["cista-files"] = JSON.stringify(tree)
}

export const connect = (path: string, handlers: Partial<Record<keyof WebSocketEventMap, any>>) => {
  const webSocket = new WebSocket(new URL(path, location.origin.replace(/^http/, 'ws')))
  for (const [event, handler] of Object.entries(handlers)) webSocket.addEventListener(event, handler)
  return webSocket
}

export const watchConnect = () => {
  if (watchTimeout !== null) {
    clearTimeout(watchTimeout)
    watchTimeout = null
  }
  const store = useMainStore()
  if (store.error !== 'Reconnecting...') store.error = 'Connecting...'
  console.log(store.error)

  wsWatch = connect(watchUrl, {
    message: handleWatchMessage,
    close: watchReconnect,
  })
  wsWatch.addEventListener("message", event => {
    if (store.connected) return
    const msg = JSON.parse(event.data)
    if ('error' in msg) {
      if (msg.error.code === 401) {
        store.user.isLoggedIn = false
        store.dialog = 'login'
      } else {
        store.error = msg.error.message
      }
      return
    }
    if ("server" in msg) {
      console.log('Connected to backend', msg)
      store.server = msg.server
      store.connected = true
      reconnDelay = 500
      store.error = ''
      if (msg.user) store.login(msg.user.username, msg.user.privileged)
      else if (store.isUserLogged) store.logout()
      if (!msg.server.public && !msg.user) store.dialog = 'login'
    }
  })
}

export const watchDisconnect = () => {
  if (!wsWatch) return
  wsWatch.close()
  wsWatch = null
}

let watchTimeout: any = null

const watchReconnect = (event: MessageEvent) => {
  const store = useMainStore()
  if (store.connected) {
    console.warn("Disconnected from server", event)
    store.connected = false
    store.error = 'Reconnecting...'
  }
  if (watchTimeout !== null) clearTimeout(watchTimeout)
  // Don't hammer the server while on login dialog
  if (store.dialog === 'login') {
    watchTimeout = setTimeout(watchReconnect, 100)
    return
  }
  reconnDelay = Math.min(5000, reconnDelay + 500)
  // The server closes the websocket after errors, so we need to reopen it
  watchTimeout = setTimeout(watchConnect, reconnDelay)
}


const handleWatchMessage = (event: MessageEvent) => {
  const msg = JSON.parse(event.data)
  switch (true) {
    case !!msg.root:
      handleRootMessage(msg)
      break
    case !!msg.update:
      handleUpdateMessage(msg)
      break
    case !!msg.space:
      console.log('Watch space', msg.space)
      break
    case !!msg.error:
      handleError(msg)
      break
    default:
  }
}

function handleRootMessage({ root }: { root: FileEntry[] }) {
  const store = useMainStore()
  console.log('Watch root', root)
  store.updateRoot(root)
  tree = root
  saveSession()
}

function handleUpdateMessage(updateData: { update: UpdateEntry[] }) {
  const store = useMainStore()
  const update = updateData.update
  console.log('Watch update', update)
  if (!tree) return console.error('Watch update before root')
  let newtree = []
  let oidx = 0

  for (const [action, arg] of update) {
    if (action === 'k') {
      newtree.push(...tree.slice(oidx, oidx + arg))
      oidx += arg
    }
    else if (action === 'd') oidx += arg
    else if (action === 'i') newtree.push(...arg)
    else console.log("Unknown update action", action, arg)
  }
  if (oidx != tree.length)
    throw Error(`Tree update out of sync, number of entries mismatch: got ${oidx}, expected ${tree.length}, new tree ${newtree.length}`)
  store.updateRoot(newtree)
  tree = newtree
  saveSession()
}

function handleError(msg: errorEvent) {
  const store = useMainStore()
  if (msg.error.code === 401) {
    store.user.dialog = 'login'
    store.user.isLoggedIn = false
    return
  }
}
