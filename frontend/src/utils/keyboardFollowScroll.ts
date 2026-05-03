type ScrollOptions = {
  topPad?: number
  bottomPad?: number
  keyboardWindowMs?: number
  getScrollContainer?: () => HTMLElement | null
}

export function createKeyboardFollowScroll(options: ScrollOptions = {}) {
  const {
    topPad = 84,
    bottomPad = 84,
    keyboardWindowMs = 260,
    getScrollContainer = () =>
      (document.querySelector('main') as HTMLElement | null) ?? document.documentElement
  } = options

  let scrollAnimationFrame: number | null = null
  let scrollTargetY: number | null = null
  let scrollVelocity = 0
  let keyboardFollowUntil = 0

  const markKeyboardFollow = () => {
    keyboardFollowUntil = performance.now() + keyboardWindowMs
  }

  const keyboardFollowActive = () => performance.now() < keyboardFollowUntil

  const clampScrollY = (y: number, scroller: HTMLElement) => {
    const maxY = Math.max(0, scroller.scrollHeight - scroller.clientHeight)
    return Math.min(maxY, Math.max(0, y))
  }

  const cursorScrollTarget = (el: HTMLElement): number | null => {
    const scroller = getScrollContainer() ?? document.documentElement
    const rect = el.getBoundingClientRect()
    const scrollerRect = scroller.getBoundingClientRect()
    const visibleTop = scrollerRect.top + topPad
    const visibleBottom = scrollerRect.bottom - bottomPad

    if (rect.top >= visibleTop && rect.bottom <= visibleBottom) return null

    if (rect.top < visibleTop) {
      return clampScrollY(scroller.scrollTop + (rect.top - visibleTop), scroller)
    }

    return clampScrollY(scroller.scrollTop + (rect.bottom - visibleBottom), scroller)
  }

  const runSmoothCursorScroll = () => {
    if (scrollAnimationFrame != null) return

    const step = () => {
      const scroller = getScrollContainer() ?? document.documentElement

      if (scrollTargetY == null) {
        scrollVelocity *= 0.68
        if (Math.abs(scrollVelocity) > 0.05) {
          const next = clampScrollY(scroller.scrollTop + scrollVelocity, scroller)
          scroller.scrollTop = next
          scrollAnimationFrame = requestAnimationFrame(step)
          return
        }
        scrollVelocity = 0
        scrollAnimationFrame = null
        return
      }

      const current = scroller.scrollTop
      const delta = scrollTargetY - current
      const absDelta = Math.abs(delta)
      if (absDelta < 0.6 && Math.abs(scrollVelocity) < 0.08) {
        scroller.scrollTop = scrollTargetY
        scrollVelocity = 0
        scrollTargetY = null
        scrollAnimationFrame = null
        return
      }

      const stiffness = Math.min(0.022, 0.01 + absDelta / 10000)
      const damping = 0.76
      scrollVelocity += delta * stiffness
      scrollVelocity *= damping

      const next = clampScrollY(current + scrollVelocity, scroller)
      if (next === current) scrollVelocity = 0
      scroller.scrollTop = next
      scrollAnimationFrame = requestAnimationFrame(step)
    }

    scrollAnimationFrame = requestAnimationFrame(step)
  }

  const keepVisible = (el: HTMLElement | null) => {
    if (!keyboardFollowActive()) {
      scrollTargetY = null
      scrollVelocity = 0
      return
    }

    if (!el) {
      scrollTargetY = null
      return
    }

    const target = cursorScrollTarget(el)
    if (target == null) {
      scrollTargetY = null
      return
    }

    scrollTargetY = target
    runSmoothCursorScroll()
  }

  const cancel = () => {
    if (scrollAnimationFrame != null) cancelAnimationFrame(scrollAnimationFrame)
    scrollAnimationFrame = null
    scrollTargetY = null
    scrollVelocity = 0
    keyboardFollowUntil = 0
  }

  return { markKeyboardFollow, keepVisible, cancel }
}
