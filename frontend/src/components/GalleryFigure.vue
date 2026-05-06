<template>
  <a :id="`file-${doc.key}`" :href=doc.url tabindex=-1
    :class="{ file: !doc.dir, folder: doc.dir, cursor: store.cursor === doc.key, ghost: doc.ghost }"
    @contextmenu.stop
    @focus.stop="store.cursor = doc.key"
    @click=onclick
    @mouseenter="tooltip?.startHover"
    @mousemove="tooltip?.updatePosition"
    @mouseleave="tooltip?.endHover"
  >
    <figure>
      <slot></slot>
      <MediaPreview :key="snap.ext" ref=m :doc="doc" tabindex=-1 quality="sz=512" class="figcontent" />
      <div class="titlespacer"></div>
      <figcaption @click.prevent @contextmenu.prevent="$emit('menu', $event)">
        <template v-if="editing">
          <SelectBox :doc=doc @click="store.cursor = doc.key"/>
          <div class="filename-row rename-row">
            <div class="rename-wrap">
              <FileRenameInput :doc=doc :rename=editing.rename :exit=editing.exit />
            </div>
          </div>
          <div class=namespacer></div>
        </template>
        <template v-else>
          <SelectBox :doc=doc @click="store.cursor = doc.key"/>
          <div class="filename-row">
            <span class="filename-group">
              <span class="filename">{{ snap.displayName }}<SparseIndicator :doc="doc" class="after-name" /></span>
              <span v-if="snap.ext" class="file-ext">.{{ snap.ext }}</span>
            </span>
            <button class="rename-btn" @click="$emit('rename')" title="Rename">✏️</button>
          </div>
          <div class=namespacer></div>
        </template>
      </figcaption>
    </figure>
    <CursorTooltip ref="tooltip" :text="tooltipText">
      <div class="tooltip-name">{{ snap.name }}</div>
      <div class="tooltip-details">{{ doc.modified }} — {{ doc.sizedisp }}</div>
      <div v-if="doc.sparseIndicator" class="tooltip-sparse">{{ sparseText }}</div>
    </CursorTooltip>
  </a>
</template>

<script setup lang="ts">
import MediaPreview from '@/components/MediaPreview.vue'
import { Doc } from '@/repositories/Document'
import { useMainStore } from '@/stores/main'
import { formatSize } from '@/utils'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import CursorTooltip from './CursorTooltip.vue'
import SparseIndicator from './SparseIndicator.vue'

const store = useMainStore()
const router = useRouter()
type EditingProp = {
  rename: (doc: Doc, newName: string) => void
  exit: () => void
}

const props = defineProps<{
  doc: Doc
  editing?: EditingProp
}>()
const m = ref<typeof MediaPreview | null>(null)
const tooltip = ref<InstanceType<typeof CursorTooltip> | null>(null)

const tooltipText = computed(() => props.doc.key)

const sparseText = computed(() => {
  const { size, allocated } = props.doc
  return `${formatSize(allocated)} allocated of ${formatSize(size)}`
})

// Single subscription to docVersion; all doc-derived values come from here.
// This is needed because Doc instances are non-reactive plain objects, so
// mutating doc.name alone won't invalidate computed caches.
const snap = computed(() => {
  void store.docVersion
  const { name, ext } = props.doc
  const base = ext ? name.slice(0, name.length - ext.length - 1) : name
  return {
    name,
    ext,
    displayName: base.replace(/[_.]+/g, ' ')
  }
})

const onclick = (ev: Event) => {
  if (m.value!.play()) {
    ev.preventDefault()
  } else if (props.doc.text) {
    ev.preventDefault()
    router.push(props.doc.editurl.replace('/#', ''))
  }
  store.cursor = props.doc.key
}
</script>

<style scoped>
.tooltip-name {
  font-weight: 600;
  text-align: center;
}
.tooltip-details {
  text-align: center;
}
.tooltip-sparse {
  text-align: center;
  opacity: 0.8;
}
.after-name {
  margin-left: 0.3em;
}
.filename-row {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  flex: 0 1 auto;
  min-width: 0;
  position: relative;
  overflow: visible;
  max-width: calc(100% - 4.5em);
}
.filename-row::after {
  content: '';
  position: absolute;
  left: 100%;
  top: 0;
  width: 1.4em;
  height: 100%;
}
.filename-group {
  display: inline-flex;
  align-items: baseline;
  min-width: 0;
  max-width: 100%;
}
.filename {
  cursor: default;
  padding: .5em 0;
  color: #fff;
  font-size: 0.8em;
  font-weight: 600;
  text-shadow: 0 0 .2em #000, 0 0 .2em #000;
  text-wrap: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
  flex: 0 1 auto;
  min-width: 0;
}
.file-ext {
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.8em;
  font-weight: 600;
  text-shadow: 0 0 .2em #000, 0 0 .2em #000;
  padding: 0 .15em 0 0;
  white-space: nowrap;
  flex: 0 0 auto;
}
.rename-btn {
  position: absolute;
  left: 100%;
  top: 50%;
  transform: translate(0.2em, -50%);
  z-index: 2;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: 0.8em;
  line-height: 1;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 0.12s ease;
}
.filename-row:hover .rename-btn {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
}
figure {
  height: var(--gallery-figure-height, 15em);
  max-height: var(--gallery-figure-height, 15em);
  position: relative;
  border-radius: .5em;
  overflow: hidden;
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: height 0.4s ease, max-height 0.4s ease;
}
figure > article {
  flex: 0 0 auto;
}
figure :deep(.video-container) {
  height: var(--gallery-figure-height, 15em);
}
.titlespacer {
  flex-shrink: 100000;
  width: 100%;
  height: 2em;
}
figcaption {
  position: absolute;
  overflow: hidden;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
}
figcaption input[type='checkbox'] {
  width: 1.1em;
  height: 1.1em;
  margin: .25em .4em .25em .35em;
  opacity: 0;
  flex-shrink: 0;
  transition: opacity var(--transition-time) ease-in-out;
}
figcaption input[type='checkbox']:checked, figcaption:hover input[type='checkbox'] {
  opacity: 1;
}
.cursor .filename {
  color: var(--accent-color);
}
.cursor .file-ext {
  color: var(--accent-color);
}
figcaption .namespacer {
  flex-shrink: 100000;
  height: 2em;
  width: 2em;
}
.rename-wrap {
  font-size: 0.8em;
  width: auto;
  min-width: 0;
  max-width: 100%;
}
.rename-row {
  max-width: calc(100% - 4.5em);
}
.rename-wrap :deep(#FileRenameInput) {
  min-width: 0;
  max-width: 100%;
}
</style>
