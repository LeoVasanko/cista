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
      <MediaPreview ref=m :doc="doc" tabindex=-1 quality="sz=512" class="figcontent" />
      <div v-if="!doc.dir && doc.ext" class="ext-badge">{{ doc.ext }}</div>
      <div class="titlespacer"></div>
      <figcaption @click.prevent @contextmenu.prevent="$emit('menu', $event)">
        <template v-if="editing">
          <div class="rename-wrap">
            <FileRenameInput :doc=doc :rename=editing.rename :exit=editing.exit />
          </div>
        </template>
        <template v-else>
          <SelectBox :doc=doc @click="store.cursor = doc.key"/>
          <span>{{ displayName }}<SparseIndicator :doc="doc" class="after-name" /></span>
          <div class=namespacer></div>
        </template>
      </figcaption>
    </figure>
    <CursorTooltip ref="tooltip" :text="tooltipText">
      <div class="tooltip-name">{{ doc.name }}</div>
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
import CursorTooltip from './CursorTooltip.vue'
import SparseIndicator from './SparseIndicator.vue'

const store = useMainStore()
type EditingProp = {
  rename: (name: string) => void
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

const displayName = computed(() => {
  const { name, ext } = props.doc
  const base = ext ? name.slice(0, name.length - ext.length - 1) : name
  return base.replace(/[_.]+/g, ' ')
})

const onclick = (ev: Event) => {
  if (m.value!.play()) ev.preventDefault()
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
.ext-badge {
  position: absolute;
  bottom: 2.5em;
  right: 1em;
  color: #fff;
  font-size: 0.65em;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  text-shadow: 0 0 .2em #000, 0 0 .2em #000;
  line-height: 1.4;
  pointer-events: none;
  user-select: none;
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
  width: 1.5em;
  height: 1.5em;
  margin: .25em 0 .25em .25em;
  opacity: 0;
  flex-shrink: 0;
  transition: opacity var(--transition-time) ease-in-out;
}
figcaption input[type='checkbox']:checked, figcaption:hover input[type='checkbox'] {
  opacity: 1;
}
figcaption span {
  cursor: default;
  padding: .5em;
  color: #fff;
  font-size: 0.8em;
  font-weight: 600;
  text-shadow: 0 0 .2em #000, 0 0 .2em #000;
  text-wrap: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.cursor figcaption span {
  color: var(--accent-color);
}
figcaption .namespacer {
  flex-shrink: 100000;
  height: 2em;
  width: 2em;
}
.rename-wrap {
  font-size: 0.8em;
  width: 100%;
}
</style>
