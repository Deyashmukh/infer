import { defineConfig, mergeConfig } from 'vite'
import { defineConfig as defineVitestConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const vitestConfig = defineVitestConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})

export default mergeConfig(
  defineConfig({
    plugins: [react()],
  }),
  vitestConfig,
)
