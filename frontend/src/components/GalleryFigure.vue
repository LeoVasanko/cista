<template>
  <a :id="`file-${doc.key}`" :href=doc.url tabindex=-1
    :class="{ file: !doc.dir, folder: doc.dir, cursor: store.cursor === doc.key }"
    @contextmenu.stop
    @focus.stop="store.cursor = doc.key"
    @click="ev => {
      if (m!.play()) ev.preventDefault()
      store.cursor = doc.key
    }"
  >
    <figure>
      <slot></slot>
      <MediaPreview ref=m :doc="doc" tabindex=-1 quality="sz=512" />
      <caption>
        <label>
          <SelectBox :doc=doc />
          <span :title="doc.name + '\n' + doc.modified + '\n' + doc.sizedisp">{{ doc.name }}</span>
        </label>
      </caption>
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
</script>

<style scoped>
.gallery figure {
  height: 15rem;
  position: relative;
  border-radius: .5rem;
  overflow: hidden;
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  overflow: hidden;
}
figure caption {
  font-weight: 600;
  color: var(--text-color);
  text-shadow: 0 0 .2rem var(--primary-background), 0 0 .2rem var(--primary-background);
}
.cursor caption {
  background: var(--accent-color);
  text-shadow: none;
}
caption {
  position: absolute;
  overflow: hidden;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}
caption label {
  width: 100%;
  display: flex;
  align-items: center;
}
label span {
  flex: 1 1;
  margin-right: 2rem;
  text-align: center;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
label input[type='checkbox'] {
  width: 2rem;
  height: 2rem;
  opacity: 0;
  flex-shrink: 0;
}
label input[type='checkbox']:checked {
  opacity: 1;
}
a {
  text-decoration: none;
}

</style>
