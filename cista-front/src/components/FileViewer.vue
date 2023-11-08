<template>
  <object
    v-if="props.type === 'pdf'"
    :data="dataURL"
    type="application/pdf"
    width="100%"
    height="100%"
  ></object>
  <a-image
    v-else-if="props.type === 'image'"
    width="50%"
    :src="dataURL"
    @click="() => setVisible(true)"
    :previewMask="false"
    :preview="{
      visibleImg,
      onVisibleChange: setVisible
    }"
  />
  <!-- Unknown case -->
  <h1 v-else>Unsupported file type</h1>
</template>

<script setup lang="ts">
import { watchEffect, ref } from 'vue'
import Router from '@/router/index'
import { url_document_get } from '@/repositories/Document'

const dataURL = ref('')
watchEffect(() => {
  dataURL.value = new URL(
    url_document_get + Router.currentRoute.value.path,
    location.origin
  ).toString()
})
const emit = defineEmits({
  visibleImg(value: boolean) {
    return value
  }
})

function setVisible(value: boolean) {
  emit('visibleImg', value)
}

const props = defineProps<{
  type?: string
  visibleImg: boolean
}>()
</script>

<style></style>
