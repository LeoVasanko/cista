<template>
  <img v-if=doc.img :src="preview() ? doc.previewurl : doc.url" alt="">
  <span v-else-if=doc.dir class="folder icon"></span>
  <video ref=vid v-else-if=video() :src=doc.url controls preload=none @click.prevent>📄</video>
  <audio ref=aud v-else-if=audio() :src=doc.url controls preload=metadata @click.stop>📄</audio>
  <span v-else-if=archive() class="archive icon"></span>
  <span v-else class="file icon" :class="`ext-${doc.ext}`"></span>
</template>

<script setup lang=ts>
import { compile, computed, ref } from 'vue'
import type { Doc } from '@/repositories/Document'

const aud = ref<HTMLAudioElement | null>(null)
const vid = ref<HTMLVideoElement | null>(null)
const media = computed(() => aud.value || vid.value)
const props = defineProps<{
  doc: Doc
}>()

defineExpose({
  play() {
    if (media.value) {
      if (media.value.paused) media.value.play()
      else media.value.pause()
      return true
    }
    return false
  },
})


const video = () => ['mkv', 'mp4', 'webm', 'mov', 'avi'].includes(props.doc.ext)
const audio = () => ['mp3', 'flac', 'ogg', 'aac'].includes(props.doc.ext)
const archive = () => ['zip', 'tar', 'gz', 'bz2', 'xz', '7z', 'rar'].includes(props.doc.ext)
const preview = () => (
  props.doc.size > 500000 &&
  ['png', 'bmp', 'ico', 'webp', 'avif', 'jpg', 'jpeg'].includes(props.doc.ext)
)
</script>

<style scoped>
img, embed, .icon {
  font-size: 10em;
  border-radius: .5rem;
  overflow: hidden;
  text-align: center;
  object-fit: cover;
  object-position: center;
  min-width: 50%;
  height: 100%;
}
audio, video {
  height: 100%;
  min-width: 50%;
  max-width: 100%;
  padding-bottom: 2rem;
  margin: auto;
}
.folder::before {
  content: '📁';
}
.folder:hover::before, .cursor .folder::before {
  content: '📂';
}
.archive::before {
  content: '📦';
}
.file::before {
  content: '📄';
}
.ext-img::before {
  content: '💿';
}
.ext-exe::before, .ext-msi::before, .ext-dmg::before, .ext-pkg::before {
  content: '⚙️';
}
.ext-torrent::before {
  content: '🏴‍☠️';
}
.icon {
  filter: brightness(0.9);
}
figure.cursor .icon {
  filter: brightness(1);
}
img::before, video::before {
  /* broken image */
  background: #888;
  position: absolute;
  width: 100%;
  height: 100%;
  top: 0;
  left: 0;
  text-align: center;
  text-shadow: 0 0 .5rem #000;
  filter: grayscale(1);
  content: '❌';
}
</style>
