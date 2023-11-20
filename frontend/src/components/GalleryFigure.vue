<template>
  <a :id="`file-${doc.key}`" :href=doc.url tabindex=-1
    :class="{ file: !doc.dir, folder: doc.dir, cursor: store.cursor === doc.key }"
    @contextmenu.stop
    @focus.stop="store.cursor = doc.key"
    @click=onclick
  >
    <figure>
      <slot></slot>
      <MediaPreview ref=m :doc="doc" tabindex=-1 quality="sz=512" class="figcontent" />
      <div class="titlespacer"></div>
      <figcaption>
        <SelectBox :doc=doc />
        <span :title="doc.name + '\n' + doc.modified + '\n' + doc.sizedisp">{{ doc.name }}</span>
        <div class=namespacer></div>
      </figcaption>
    </figure>
  </a>
</template>

<script setup lang=ts>
import { ref } from 'vue'
import { useMainStore } from '@/stores/main'
import { Doc } from '@/repositories/Document'
import MediaPreview from '@/components/MediaPreview.vue'

const store = useMainStore()
const props = defineProps<{
  doc: Doc
  index: number
}>()
const m = ref<typeof MediaPreview | null>(null)

const onclick = (ev: Event) => {
  if (m.value!.play()) ev.preventDefault()
  store.cursor = props.doc.key
}
</script>

<style scoped>
figure {
  max-height: 15em;
  position: relative;
  border-radius: .5em;
  overflow: hidden;
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: end;
  overflow: hidden;
}
figure > article {
  flex: 0 0 auto;
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
  margin: .25em;
  opacity: 0;
  flex-shrink: 0;
}
figcaption input[type='checkbox']:checked, figcaption input[type='checkbox']:hover {
  opacity: 1;
}
figcaption span {
  padding: .5em;
  color: #fff;
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
</style>
