// SVG icon index - all icons bundled together
import AddFile from './add-file.svg'
import AddFolder from './add-folder.svg'
import Arrow from './arrow.svg'
import ArrowsH from './arrows-h.svg'
import ArrowsV from './arrows-v.svg'
import Check from './check.svg'
import Code from './code.svg'
import Cog from './cog.svg'
import Copy from './copy.svg'
import CreateFile from './create-file.svg'
import CreateFolder from './create-folder.svg'
import Cross from './cross.svg'
import Disk from './disk.svg'
import Download from './download.svg'
import Exclamation from './exclamation.svg'
import Eye from './eye.svg'
import Find from './find.svg'
import Fullscreen from './fullscreen.svg'
import Github from './github.svg'
import Home from './home.svg'
import Info from './info.svg'
import Link from './link.svg'
import Logo from './logo.svg'
import Loop from './loop.svg'
import Menu from './menu.svg'
import Next from './next.svg'
import Open from './open.svg'
import Paste from './paste.svg'
import Pause from './pause.svg'
import Pencil from './pencil.svg'
import Play from './play.svg'
import Plus from './plus.svg'
import Previous from './previous.svg'
import Reload from './reload.svg'
import Rename from './rename.svg'
import Scissors from './scissors.svg'
import Shuffle from './shuffle.svg'
import Signin from './signin.svg'
import Signout from './signout.svg'
import Skip from './skip.svg'
import Spinner from './spinner.svg'
import Stop from './stop.svg'
import Trash from './trash.svg'
import Triangle from './triangle.svg'
import Unfullscreen from './unfullscreen.svg'
import UpArrow from './up-arrow.svg'
import UploadCloud from './upload-cloud.svg'
import UserCog from './user-cog.svg'
import User from './user.svg'
import VolumeHigh from './volume-high.svg'
import VolumeLow from './volume-low.svg'
import VolumeMedium from './volume-medium.svg'
import VolumeMute from './volume-mute.svg'
import WindowCross from './window-cross.svg'
import Window from './window.svg'
import Wordwrap from './wordwrap.svg'
import Zoomin from './zoomin.svg'
import Zoomout from './zoomout.svg'

// Named exports for direct imports
export {
  AddFile,
  AddFolder,
  Arrow,
  ArrowsH,
  ArrowsV,
  Check,
  Code,
  Cog,
  Copy,
  CreateFile,
  CreateFolder,
  Cross,
  Disk,
  Download,
  Exclamation,
  Eye,
  Find,
  Fullscreen,
  Github,
  Home,
  Info,
  Link,
  Logo,
  Loop,
  Menu,
  Next,
  Open,
  Paste,
  Pause,
  Pencil,
  Play,
  Plus,
  Previous,
  Reload,
  Rename,
  Scissors,
  Shuffle,
  Signin,
  Signout,
  Skip,
  Spinner,
  Stop,
  Trash,
  Triangle,
  Unfullscreen,
  UpArrow,
  UploadCloud,
  UserCog,
  User,
  VolumeHigh,
  VolumeLow,
  VolumeMedium,
  VolumeMute,
  WindowCross,
  Window,
  Wordwrap,
  Zoomin,
  Zoomout
}

// Icon lookup by kebab-case name (for SvgButton compatibility)
export const icons = {
  'add-file': AddFile,
  'add-folder': AddFolder,
  arrow: Arrow,
  'arrows-h': ArrowsH,
  'arrows-v': ArrowsV,
  check: Check,
  code: Code,
  cog: Cog,
  copy: Copy,
  'create-file': CreateFile,
  'create-folder': CreateFolder,
  cross: Cross,
  disk: Disk,
  download: Download,
  exclamation: Exclamation,
  eye: Eye,
  find: Find,
  fullscreen: Fullscreen,
  github: Github,
  home: Home,
  info: Info,
  link: Link,
  logo: Logo,
  loop: Loop,
  menu: Menu,
  next: Next,
  open: Open,
  paste: Paste,
  pause: Pause,
  pencil: Pencil,
  play: Play,
  plus: Plus,
  previous: Previous,
  reload: Reload,
  rename: Rename,
  scissors: Scissors,
  shuffle: Shuffle,
  signin: Signin,
  signout: Signout,
  skip: Skip,
  spinner: Spinner,
  stop: Stop,
  trash: Trash,
  triangle: Triangle,
  unfullscreen: Unfullscreen,
  'up-arrow': UpArrow,
  'upload-cloud': UploadCloud,
  'user-cog': UserCog,
  user: User,
  'volume-high': VolumeHigh,
  'volume-low': VolumeLow,
  'volume-medium': VolumeMedium,
  'volume-mute': VolumeMute,
  'window-cross': WindowCross,
  window: Window,
  wordwrap: Wordwrap,
  zoomin: Zoomin,
  zoomout: Zoomout
} as const

export type IconName = keyof typeof icons
