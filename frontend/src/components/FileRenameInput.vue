<template>
  <input
    ref="input"
    id="FileRenameInput"
    type="text"
    autocorrect="off"
    v-model="name"
    @blur="exit"
    @keyup.esc="exit"
    @keyup.enter="apply"
  />
</template>

<script setup lang="ts">
import { Doc } from '@/repositories/Document'
import { ref, onMounted, nextTick } from 'vue'

const input = ref<HTMLInputElement | null>(null)
const name = ref('')

onMounted(() => {
  name.value = props.doc.name
  const ext = name.value.lastIndexOf('.')
  nextTick(() => {
    input.value!.focus()
    input.value!.setSelectionRange(0, ext > 0 ? ext : name.value.length)
  })
})

const props = defineProps<{
  doc: Doc
  rename: (doc: Doc, newName: string) => void
  exit: () => void
}>()

const apply = () => {
  props.exit()
  if (
    props.doc.key !== 'new' &&
    (name.value === props.doc.name || name.value.length === 0)
  )
    return
  props.rename(props.doc, name.value)
}
</script>

<style>
input#FileRenameInput {
  color: var(--input-color);
  background: var(--input-background);
  border: 0;
  border-radius: 0.3rem;
  padding: 0.4rem;
  margin: -0.4rem;
  width: 100%;
  outline: none;
  font: inherit;
}
</style>
