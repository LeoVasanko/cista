<template>
  <template v-for="upload in documentStore.uploadingDocuments" :key="upload.key">
    <span>{{ upload.name }}</span>
    <div class="progress-container">
      <a-progress :percent="upload.progress" />
      <CloseCircleOutlined class="close-button" @click="dismissUpload(upload.key)" />
    </div>
  </template>
</template>
<script setup lang="ts">
import { useDocumentStore } from '@/stores/documents'
const documentStore = useDocumentStore()

function dismissUpload(key: number) {
  documentStore.deleteUploadingDocument(key)
}
</script>

<style scoped>
.progress-container {
  display: flex;
  align-items: center;
}
.close-button:hover {
  color: #b81414;
}
</style>
