import { useMainStore } from "@/stores/main"
import { useSsoAuthStore } from "@/stores/ssoAuth"
import { showAuthIframe, AuthCancelledError, isAuthIframeOpen } from 'paskia'
import type { FileEntry, UpdateEntry, errorEvent } from "./Document"

export const controlUrl = '/api/control'
export const uploadUrl = '/api/upload'
export const watchUrl = '/api/watch'

let tree = [] as FileEntry[]
let reconnDelay = 500
let wsWatch = null as WebSocket | null
// Track when we're awaiting authentication to prevent reconnection loops
let awaitingAuth = false

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

// Handle auth error from WebSocket - show paskia iframe and reconnect on success
async function handleWsAuthError(msg: any) {
  const iframe = msg.error?.auth?.iframe
  if (iframe) {
    // Stop reconnection attempts while showing auth dialog
    awaitingAuth = true
    if (watchTimeout !== null) {
      clearTimeout(watchTimeout)
      watchTimeout = null
    }
    try {
      await showAuthIframe(iframe)
      // Auth succeeded - reconnect
      awaitingAuth = false
      watchConnect()
    } catch (e) {
      awaitingAuth = false
      if (e instanceof AuthCancelledError) {
        console.log('User cancelled authentication')
        // User cancelled - don't automatically retry, wait for user action
      } else {
        console.error('Auth iframe error:', e)
      }
    }
    return true
  }
  return false
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
      if (msg.error.code === 401 || msg.error.code === 403) {
        // Show paskia auth iframe (works for both password and paskia modes)
        handleWsAuthError(msg)
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
      // Start SSO validation polling only in paskia mode
      if (msg.server.authentication === 'paskia') {
        const ssoStore = useSsoAuthStore()
        ssoStore.startValidationPolling()
      }
    }
  })
}

export const watchDisconnect = () => {
  if (!wsWatch) return
  wsWatch.close()
  wsWatch = null
}

// Reset auth state and reconnect - call after successful authentication
export const resumeWatching = () => {
  awaitingAuth = false
  if (watchTimeout !== null) {
    clearTimeout(watchTimeout)
    watchTimeout = null
  }
  watchConnect()
}

let watchTimeout: any = null

const watchReconnect = (event: MessageEvent) => {
  const store = useMainStore()
  // Don't reconnect if we're awaiting authentication or auth iframe is showing
  if (awaitingAuth || isAuthIframeOpen()) {
    console.log('Skipping reconnect - awaiting authentication')
    return
  }
  if (store.connected) {
    console.warn("Disconnected from server", event)
    store.connected = false
    store.error = 'Reconnecting...'
  }
  if (watchTimeout !== null) clearTimeout(watchTimeout)
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
  if (msg.error.code === 401 || msg.error.code === 403) {
    // Show paskia auth iframe (works for both password and paskia modes)
    handleWsAuthError(msg as any)
    return
  }
}
