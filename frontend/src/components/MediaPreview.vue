<template>
  <img v-if=preview() :src="`${doc.previewurl}?${quality}&t=${doc.mtime}`" alt="">
  <img v-else-if=doc.img :src=doc.url alt="">
  <span v-else-if=doc.dir class="folder icon"></span>
  <video ref=vid v-else-if=video() :src=doc.url :poster=poster preload=none @play=onplay @pause=onpaused @ended=next @seeking=media!.play()></video>
  <div v-else-if=audio() class="audio icon">
    <audio ref=aud :src=doc.url class=icon preload=none @play=onplay @pause=onpaused @ended=next @seeking=media!.play()></audio>
  </div>
  <span v-else-if=archive() class="archive icon"></span>
  <span v-else class="file icon" :class="`ext-${doc.ext}`"></span>
</template>

<script setup lang=ts>
import { compile, computed, ref } from 'vue'
import type { Doc } from '@/repositories/Document'

const aud = ref<HTMLAudioElement | null>(null)
const vid = ref<HTMLVideoElement | null>(null)
const media = computed(() => aud.value || vid.value)
const poster = computed(() => `${props.doc.previewurl}?${props.quality}&t=${props.doc.mtime}`)
const props = defineProps<{
  doc: Doc
  quality: string
}>()

const onplay = () => {
  if (!media.value) return
  media.value.controls = true
  media.value.setAttribute('data-playing', '')
}
const onpaused = () => {
  if (!media.value) return
  media.value.controls = false
  media.value.removeAttribute('data-playing')
}
let fscurrent: HTMLVideoElement | null = null
const next = () => {
  if (!media.value) return
  media.value.load()  // Restore poster
  const medias = Array.from(document.querySelectorAll('video, audio')) as (HTMLAudioElement | HTMLVideoElement)[]
  if (medias.length === 0) return
  let el: HTMLAudioElement | HTMLVideoElement | null = null
  for (const i in medias) {
    if (medias[i] === (fscurrent || media.value)) {
      el = medias[+i + 1] || medias[0]
      break
    }
  }
  if (!el) return
  if (el.tagName === "VIDEO" && document.fullscreenElement === media.value) {
    // Fullscreen needs to use the current video element for the next video
    // because we are not allowed to fullscreen the next one.
    // FIXME: Write our own player to avoid this problem...
    const elem = media.value as HTMLVideoElement
    const playing = el as HTMLVideoElement
    if (elem === playing) {
      playing.play()  // Only one video, just replay
      return
    }
    if (!fscurrent) {
      elem.addEventListener('fullscreenchange', ev => {
        if (!fscurrent) return
        // Restore the original video element and continue with the one that was playing
        fscurrent.currentTime = elem.currentTime
        fscurrent.click()
        if (!elem.paused) fscurrent.play()
        fscurrent = null
        elem.src = props.doc.url
        elem.poster = poster.value
        onpaused()
      }, {once: true})
    }
    fscurrent = playing
    elem.src = playing.src
    elem.poster = ''
    elem.play()
  } else {
    document.exitFullscreen()
    el.click()
  }
}
defineExpose({
  play() {
    if (!media.value) return false
    if (media.value.paused) {
      media.value.play()
      for (const el of Array.from(document.querySelectorAll('video, audio')) as (HTMLAudioElement | HTMLVideoElement)[]) {
        if (el === media.value) continue
        el.pause()
      }
    } else {
      media.value.pause()
    }
    return true
  },
  media,
})


const video = () => ['mkv', 'mp4', 'webm', 'mov', 'avi'].includes(props.doc.ext)
const audio = () => ['mp3', 'flac', 'ogg', 'aac'].includes(props.doc.ext)
const archive = () => ['zip', 'tar', 'gz', 'bz2', 'xz', '7z', 'rar'].includes(props.doc.ext)
const preview = () => (
  ['bmp', 'ico', 'tif', 'tiff', 'pdf'].includes(props.doc.ext) ||
  props.doc.size > 500000 &&
  ['avif', 'webp', 'png', 'jpg', 'jpeg'].includes(props.doc.ext)
)
</script>

<style scoped>
img, embed, .icon, audio, video {
  font-size: 8em;
  overflow: hidden;
  min-width: 50%;
  max-width: 100%;
  max-height: 100%;
  border-radius: calc(.5em / 8);
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
.audio audio {
  opacity: 0;
  transition: opacity var(--transition-time) ease-in-out;
}
.audio:hover audio {
  opacity: 1;
}
.audio.icon::before {
  width: 100%;
  content: '🔈';
}
.audio.icon:has(audio[data-playing])::before {
  position: absolute;
  content: '🔊';
  bottom: 0;
}
.icon {
  filter: brightness(0.9);
}
figure.cursor .icon {
  filter: brightness(1);
}
img::before, video::before {
  /* broken media */
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
