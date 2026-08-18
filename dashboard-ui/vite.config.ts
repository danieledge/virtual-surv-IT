import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Single-file, zero-server build: the whole app (JS + CSS + the Python-emitted JSON data,
// statically imported at build time) compiles to one dist/index.html - double-click it open,
// no `npm run dev`, no server. vite-plugin-singlefile inlines everything as an INLINE
// `<script type="module">` (not an external src=) - that's what actually avoids the file://
// module-script CORS trap: the restriction blocks a module fetching ANOTHER file cross-origin,
// not an inline script with no external imports left after bundling. `base: './'` is a second,
// independent defense - any relative asset reference that somehow survives resolves against the
// file's own folder instead of breaking under an assumed http(s) root.
export default defineConfig({
  base: './',
  plugins: [react(), viteSingleFile()],
})
