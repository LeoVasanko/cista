<template>
  <nav class="headermain">
    <div class="buttons">
      <template v-if="store.error">
        <div class="error-message" @click="store.error = ''">{{ store.error }}</div>
        <div class="smallgap"></div>
      </template>
      <UploadButton :path="props.path" />
      <SvgButton
        name="create-folder"
        data-tooltip="New folder"
        @click="() => store.fileExplorer!.newFolder()"
      />
      <slot></slot>
      <div class="spacer smallgap"></div>
      <template v-if="showSearchInput">
        <input
          ref="search"
          type="search"
          :value="query"
          @input="updateSearch"
          placeholder="Search words"
          class="margin-input"
          @keyup.escape="closeSearch"
        />
      </template>
      <SvgButton ref="searchButton" name="find" @click.prevent="toggleSearchInput" />
      <SvgButton name="cog" @click="settingsMenu" />
    </div>
  </nav>
</template>

<script setup lang="ts">
import { useMainStore } from '@/stores/main'
import { ref, nextTick, watchEffect } from 'vue'
import ContextMenu from '@imengyu/vue3-context-menu'
import router from '@/router';

const store = useMainStore()
const showSearchInput = ref<boolean>(false)
const search = ref<HTMLInputElement | null>()
const searchButton = ref<HTMLButtonElement | null>()
  const props = defineProps<{
  path: Array<string>
  query: string
}>()

const closeSearch = (ev: Event) => {
  if (!showSearchInput.value) return  // Already closing
  showSearchInput.value = false
  const breadcrumb = document.querySelector('.breadcrumb') as HTMLElement
  breadcrumb.focus()
  updateSearch(ev)
}
const updateSearch = (ev: Event) => {
  const q = (ev.target as HTMLInputElement).value
  let p = props.path.join('/')
  p = p ? `/${p}` : ''
  const url = q ? `${p}//${q}` : (p || '/')
  const u = url.replaceAll('?', '%3F').replaceAll('#', '%23')
  if (!props.query && q) router.push(u)
  else router.replace(u)
}
const toggleSearchInput = (ev: Event) => {
  showSearchInput.value = !showSearchInput.value
  if (!showSearchInput.value) return closeSearch(ev)
  nextTick(() => {
    const input = search.value
    if (input) input.focus()
  })
}
watchEffect(() => {
  if (props.query) showSearchInput.value = true
})
const settingsMenu = (e: Event) => {
  // show the context menu
  const items = []
  if (store.user.isLoggedIn) {
    items.push({ label: `Logout ${store.user.username ?? ''}`, onClick: () => store.logout() })
  } else {
    items.push({ label: 'Login', onClick: () => store.loginDialog() })
  }
  ContextMenu.showContextMenu({
    // @ts-ignore
    x: e.target.getBoundingClientRect().right, y: e.target.getBoundingClientRect().bottom,
    items,
  })
}
defineExpose({
  toggleSearchInput,
  closeSearch,
})
</script>

<style scoped>
.buttons {
  padding: 0;
  display: flex;
  align-items: center;
  height: 3.5em;
  z-index: 10;
}
.buttons > * {
  flex-shrink: 1;
}
input[type='search'] {
  background: var(--input-background);
  color: var(--input-color);
  border: 0;
  border-radius: 0.1em;
  padding: 0.5em;
  outline: none;
  font-size: 1.5em;
  max-width: 30vw;
}
</style>
@/stores/main
