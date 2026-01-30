<template>
  <nav
    class="breadcrumb"
    aria-label="Breadcrumb"
    @keydown.left.stop="move(-1)"
    @keydown.right.stop="move(1)"
    @keyup.enter="move(0)"
    @focus=focusCurrent
    tabindex=0
  >
    <a href="#/"
      :ref="el => setLinkRef(0, el)"
      class="home"
      :class="{ current: !!isCurrent(0) }"
      :aria-current="isCurrent(0)"
      @click.prevent="navigate(0)"
      title="/"
    >
      <component :is="home" />
    </a>
    <template v-for="(location, index) in longest" :key="index">
      <a :href="`/#/${longest.slice(0, index + 1).join('/')}/`"
        :class="{ current: !!isCurrent(index + 1) }"
        :aria-current="isCurrent(index + 1)"
        @click.prevent="navigate(index + 1)"
        :ref="el => setLinkRef(index + 1, el)"
        :title="`/${longest.slice(0, index + 1).join('/')}`"
      >{{ location }}</a>
    </template>
  </nav>
</template>

<script setup lang="ts">
import { Home } from '@/assets/svg'
import { nextTick, onBeforeUpdate, ref, watchEffect } from 'vue'
import { useRouter } from 'vue-router'
import { exists } from '@/utils/fileutil'

const home = Home
const router = useRouter()

const links = [] as Array<HTMLElement>
const setLinkRef = (index: number, el: any) => { if (el) links[index] = el }
onBeforeUpdate(() => { links.length = 1 })  // 1 to keep home

const props = defineProps<{
  path: Array<string>
  primary?: boolean
}>()

const longest = ref<Array<string>>([])

const isCurrent = (index: number) => index == props.path.length ? 'location' : undefined

const focusCurrent = () => {
  nextTick(() => {
    const index = props.path.length
    if (index < links.length) links[index]!.focus()
  })
}

const navigate = (index: number) => {
  const link = links[index]
  if (!link) throw Error(`No link at index ${index} (path: ${props.path})`)
  const url = index ? `/${longest.value.slice(0, index).join('/')}/` : '/'
  const long = longest.value.length ? `/${longest.value.join('/')}/` : '/'
  const browser = decodeURIComponent(location.hash.slice(1).split('//')[0] ?? '')
  const u = url.replaceAll('?', '%3F').replaceAll('#', '%23')
  // Clicking on current link clears the rest of the path and adds new history
  if (isCurrent(index)) { longest.value.splice(index); router.push(u) }
  // Moving along breadcrumbs doesn't create new history
  else if (long.startsWith(browser)) router.replace(u)
  // Nornal navigation from elsewhere (e.g. search result breadcrumbs)
  else router.push(u)
}

const move = (dir: number) => {
  const index = props.path.length + dir
  if (index < 0 || index > longest.value.length) return
  navigate(index)
}

watchEffect(() => {
  const longcut = longest.value.slice(0, props.path.length)
  const same = longcut.every((value, index) => value === props.path[index])
  // Navigated out of previous path, reset longest to current
  if (!same) longest.value = props.path
  else if (props.path.length > longcut.length) {
    longest.value = longcut.concat(props.path.slice(longcut.length))
  }
  else {
    // Prune deleted folders from longest
    for (let i = props.path.length; i < longest.value.length; ++i) {
      if (!exists(longest.value.slice(0, i + 1))) {
        longest.value = longest.value.slice(0, i)
        break
      }
    }
  }
  // If needed, focus primary navigation to new location
  if (props.primary) nextTick(() => {
    const act = document.activeElement as HTMLElement
    if (!act || [...links, document.body].includes(act)) focusCurrent()
  })
})
</script>

<style>
:root {
  --breadcrumb-background-odd: #2d2d2d;
  --breadcrumb-background-even: #404040;
  --breadcrumb-color: #ddd;
  --breadcrumb-hover-color: #fff;
  --breadcrumb-hover-background-odd: #25a;
  --breadcrumb-hover-background-even: #812;
  --breadcrumb-transtime: 0.3s;
}
.breadcrumb {
  flex: 1 1 auto;
  display: flex;
  min-width: 20%;
  max-width: 100%;
  min-height: 2em;
  margin: 0;
  padding: 0 1em 0 0;
  overflow: hidden;
}
.breadcrumb > a {
  flex: 0 4 auto;
  display: flex;
  align-items: center;
  margin: 0 -0.5em 0 -0.5em;
  padding: 0;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
  color: var(--breadcrumb-color);
  padding: 0.3em 1.5em;
  clip-path: polygon(0 0, 1em 50%, 0 100%, 100% 100%, 100% 0, 0 0);
  transition: all var(--breadcrumb-transtime);
}
.breadcrumb > a:first-child {
  flex: 0 0 auto;
  padding-left: 1.5em;
  padding-right: 1.7em;
  clip-path: none;
}
.breadcrumb > a:last-child {
  clip-path: polygon(
    0 0,
    calc(100% - 1em) 0,
    100% 50%,
    calc(100% - 1em) 100%,
    0 100%,
    1em 50%,
    0 0
  );
}
.breadcrumb > a:only-child {
  clip-path: polygon(
    0 0,
    calc(100% - 1em) 0,
    100% 50%,
    calc(100% - 1em) 100%,
    0 100%,
    0 0
  );
}
.breadcrumb svg {
  /* FIXME: Custom positioning to align it well; needs proper solution */
  width: 1.3em;
  height: 1.3em;
  margin: -.5em;
  fill: var(--breadcrumb-color);
  transition: fill var(--breadcrumb-transtime);
}
.breadcrumb a:nth-child(odd) {
  background: var(--breadcrumb-background-odd);
}
.breadcrumb a:nth-child(even) {
  background: var(--breadcrumb-background-even);
}
.breadcrumb a:nth-child(odd):hover,
.breadcrumb a:focus:nth-child(odd) {
  background: var(--breadcrumb-hover-background-odd);
}
.breadcrumb a:nth-child(even):hover,
.breadcrumb a:focus:nth-child(even) {
  background: var(--breadcrumb-hover-background-even);
}
.breadcrumb a:hover { color: var(--breadcrumb-hover-color) }
.breadcrumb a:hover svg { fill: var(--breadcrumb-hover-color) }
.breadcrumb a.current { color: var(--accent-color); max-width: none; flex: 0 1 auto; }
.breadcrumb a.current svg { fill: var(--accent-color) }
</style>
