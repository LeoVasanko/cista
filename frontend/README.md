# Cista Vue Frontend

The frontend is a Single-Page App implemented with Vue 3. Development uses the Vite server together with the main Python backend, but in production the latter also serves the prebuilt frontend files.

## Recommended IDE Setup

[VSCode](https://code.visualstudio.com/) + [Volar](https://marketplace.visualstudio.com/items?itemName=Vue.volar) (and disable Vetur) + [TypeScript Vue Plugin (Volar)](https://marketplace.visualstudio.com/items?itemName=Vue.vscode-typescript-vue-plugin).

## Type Support for `.vue` Imports in TS

TypeScript cannot handle type information for `.vue` imports by default, so we replace the `tsc` CLI with `vue-tsc` for type checking. In editors, we need [TypeScript Vue Plugin (Volar)](https://marketplace.visualstudio.com/items?itemName=Vue.vscode-typescript-vue-plugin) to make the TypeScript language service aware of `.vue` types.

If the standalone TypeScript plugin doesn't feel fast enough to you, Volar has also implemented a [Take Over Mode](https://github.com/johnsoncodehk/volar/discussions/471#discussioncomment-1361669) that is more performant. You can enable it by the following steps:

1. Disable the built-in TypeScript Extension
    1) Run `Extensions: Show Built-in Extensions` from VSCode's command palette
    2) Find `TypeScript and JavaScript Language Features`, right click and select `Disable (Workspace)`
2. Reload the VSCode window by running `Developer: Reload Window` from the command palette.

## Hot-Reload for Development

### Run the backend

```fish
hatch shell
cista --dev -l :8000
```

### And the Vite server (in another terminal)

```fish
cd frontend
npm install
npm run dev
```
Browse to Vite, which will proxy API requests to port 8000. Both servers live reload changes.


### Type-Check, Compile and Minify for Production

This is also called by `hatch build` during Python packaging:

```fish
npm run build
```

