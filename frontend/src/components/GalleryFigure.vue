<template>
  <a
    :href="doc.url"
    tabindex=0
    @contextmenu.prevent
    @focus.stop="store.cursor = doc"
    @click="ev => {
      if (media) { media.play(); ev.preventDefault() }
    }"
  >
    <figure
      :id="`file-${doc.key}`"
      :class="{ file: !doc.dir, folder: doc.dir, cursor: store.cursor === doc }"
      @click="store.cursor = store.cursor === doc ? null : doc"
      @click.up.stop="store.cursor = store.cursor === doc ? doc : null"
    >
      <slot></slot>
      <MediaPreview ref=media :doc="doc" />
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
import { defineProps, ref } from 'vue'
import { useMainStore } from '@/stores/main'
import { Doc } from '@/repositories/Document'
import MediaPreview from '@/components/MediaPreview.vue'

const store = useMainStore()
const props = defineProps<{
  doc: Doc
  index: number
}>()
const media = ref<typeof MediaPreview | null>(null)
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
  text-shadow: 0 0 .2rem #000, 0 0 1rem #000;
}
figure.cursor caption {
  background: var(--accent-color);
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
