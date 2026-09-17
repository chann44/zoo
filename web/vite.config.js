import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  alias: {
      // Tell Vite to map the extension-less import to the correct file
      '@novnc/novnc/core/rfb': '@novnc/novnc/core/rfb.js'
    }
})
