import { useDocumentStore } from "@/stores/documents"
import type { DirEntry, UpdateEntry, errorEvent } from "./Document"

export const controlUrl = '/api/control'
export const uploadUrl = '/api/upload'
export const watchUrl = '/api/watch'

let tree = null as DirEntry | null
let reconnectDuration = 500
let wsWatch = null as WebSocket | null

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
  const store = useDocumentStore()
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
        store.user.isOpenLoginModal = true
      } else {
        store.error = msg.error.message
      }
      return
    }
    if ("server" in msg) {
      console.log('Connected to backend', msg)
      store.connected = true
      reconnectDuration = 500
      store.error = ''
      if (msg.user) store.login(msg.user.username, msg.user.privileged)
      else if (store.isUserLogged) store.logout()
      if (!msg.server.public && !msg.user) store.user.isOpenLoginModal = true
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
  const store = useDocumentStore()
  if (store.connected) {
    console.warn("Disconnected from server", event)
    store.connected = false
    store.error = 'Reconnecting...'
  }
  reconnectDuration = Math.min(5000, reconnectDuration + 500)
  // The server closes the websocket after errors, so we need to reopen it
  if (watchTimeout !== null) clearTimeout(watchTimeout)
  watchTimeout = setTimeout(watchConnect, reconnectDuration)
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

function handleRootMessage({ root }: { root: DirEntry }) {
  const store = useDocumentStore()
  console.log('Watch root', root)
  store.updateRoot(root)
  tree = root
}

function handleUpdateMessage(updateData: { update: UpdateEntry[] }) {
  const store = useDocumentStore()
  console.log('Watch update', updateData.update)
  if (!tree) return console.error('Watch update before root')
  let node: DirEntry = tree
  for (const elem of updateData.update) {
    if (elem.deleted) {
      delete node.dir[elem.name]
      break // Deleted elements can't have further children
    }
    if (elem.name) {
      // @ts-ignore
      console.log(node, elem.name)
      node = node.dir[elem.name] ||= {}
    }
    if (elem.key !== undefined) node.key = elem.key
    if (elem.size !== undefined) node.size = elem.size
    if (elem.mtime !== undefined) node.mtime = elem.mtime
    if (elem.dir !== undefined) node.dir = elem.dir
  }
  store.updateRoot(tree)
}

function handleError(msg: errorEvent) {
  const store = useDocumentStore()
  if (msg.error.code === 401) {
    store.user.isOpenLoginModal = true
    store.user.isLoggedIn = false
    return
  }
}
