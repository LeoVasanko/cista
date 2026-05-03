<template>
  <ModalDialog name="about" title="">
    <div class="about-content">
      <div class="about-logo-pane">
        <img :src="logoUrl" alt="Cista Storage logo" class="about-logo" />
      </div>
      <div class="about-details">
        <h3 class="about-name">Cista {{ softwareVersion }}</h3>
        <p class="about-link">
          <a :href="projectUrl" target="_blank" rel="noopener noreferrer">{{ displayProjectUrl }}</a>
        </p>
        <div class="dialog-buttons about-actions">
          <div class="spacer"></div>
          <input id="close" type="reset" value="Close" class="button" @click="close" />
        </div>
      </div>
    </div>
  </ModalDialog>
</template>

<script setup lang="ts">
import logoUrl from '@/assets/logo-square.svg?url'
import ModalDialog from '@/components/ModalDialog.vue'
import { useMainStore } from '@/stores/main'
import { computed } from 'vue'

const store = useMainStore()

const softwareVersion = computed(() => store.server.version || 'unknown')
const projectUrl = 'https://git.zi.fi/Vasanko/cista-storage'
const displayProjectUrl = projectUrl.replace(/^https?:\/\//, '')

const close = () => {
  store.dialog = ''
}
</script>

<style scoped>
:deep(#about.modal-dialog) {
  overflow: hidden;
}

.about-content {
  display: grid;
  grid-template-columns: 11rem minmax(0, 1fr);
  align-items: stretch;
  width: min(35rem, 92vw);
  min-width: 0;
  min-height: 0;
  margin: -1rem;
  overflow: hidden;
}

.about-logo-pane {
  display: block;
  padding: 0;
  overflow: hidden;
}

.about-logo {
  width: 100%;
  height: auto;
  aspect-ratio: 1 / 1;
  margin: 0;
  display: block;
}

.about-details {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 1.25rem;
}

.about-name {
  margin: 0;
}

.about-link {
  margin: 0.65rem 0 1rem;
  word-break: break-word;
}

.about-actions {
  margin-top: auto;
}

@media (max-width: 40rem) {
  .about-content {
    grid-template-columns: 1fr;
    width: min(24rem, 90vw);
  }

  .about-logo-pane {
    width: 100%;
    aspect-ratio: 1 / 1;
  }

  .about-logo {
    width: 100%;
    height: 100%;
    aspect-ratio: 1 / 1;
    object-fit: contain;
  }

  .about-details {
    padding: 0.85rem;
  }
}
</style>
