<template>
  <nav
    class="breadcrumb"
    aria-label="Breadcrumb"
    @keyup.left.stop="move(-1)"
    @keyup.right.stop="move(1)"
    @focus="move(0)"
  >
    <a href="#/"
      :ref="el => setLinkRef(0, el)"
      :class="{ current: !!isCurrent(0) }"
      :aria-current="isCurrent(0)"
    >
      <component :is="home" />
    </a>
    <template v-for="(location, index) in longest" :key="index">
      <a :href="`/#/${longest.slice(0, index + 1).join('/')}/`"
        :class="{ current: !!isCurrent(index + 1) }"
        :aria-current="isCurrent(index + 1)"
        @click.prevent="navigate(index + 1)"
        :ref="el => setLinkRef(index + 1, el)"
      >{{ location }}</a>
    </template>
  </nav>
</template>

<script setup lang="ts">
import home from '@/assets/svg/home.svg'
import { onBeforeUpdate, ref, watchEffect } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const links = [] as Array<HTMLElement>
const setLinkRef = (index: number, el: any) => { if (el) links[index] = el }
onBeforeUpdate(() => { links.length = 1 })  // 1 to keep home

const props = defineProps<{
  path: Array<string>
}>()

const longest = ref<Array<string>>([])

const isCurrent = (index: number) => index == props.path.length ? 'location' : undefined

const navigate = (index: number) => {
  const link = links[index]
  if (!link) throw Error(`No link at index ${index} (path: ${props.path})`)
  link.focus()
  router.replace(`/${longest.value.slice(0, index).join('/')}`)
}

const move = (dir: number) => {
  const index = props.path.length + dir
  if (index < 0 || index > longest.value.length) return
  navigate(index)
}

watchEffect(() => {
  const longcut = longest.value.slice(0, props.path.length)
  const same = longcut.every((value, index) => value === props.path[index])
  if (!same) longest.value = props.path
  else if (props.path.length > longcut.length) {
    longest.value = longcut.concat(props.path.slice(longcut.length))
  }
})
watchEffect(() => {
  if (links.length) navigate(props.path.length)
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
  display: flex;
  list-style: none;
  margin: 0;
  padding: 0 1em 0 0;
}
.breadcrumb > a {
  margin: 0 -0.5em 0 -0.5em;
  padding: 0;
  max-width: 8em;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
  height: 1.5em;
  color: var(--breadcrumb-color);
  padding: 0.3em 1.5em;
  clip-path: polygon(0 0, 1em 50%, 0 100%, 100% 100%, 100% 0, 0 0);
  transition: all var(--breadcrumb-transtime);
}
.breadcrumb a:first-child {
  margin-left: 0;
  padding-left: .2em;
  clip-path: none;
}
.breadcrumb a:last-child {
  max-width: none;
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
.breadcrumb a:only-child {
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
  padding-left: 0.8em;
  width: 1.3em;
  height: 1.3em;
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
.breadcrumb a.current { color: var(--accent-color) }
.breadcrumb a.current svg { fill: var(--accent-color) }
</style>
