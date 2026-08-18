import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted fonts (@fontsource) - latin subset only, only the weights this file's CSS
// actually uses, to keep the single-file `dist/index.html` build reasonable in size. No CDN
// <link>: this must keep working fully offline under file://.
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/latin-700.css'
import '@fontsource/inter/latin-800.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-700.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
