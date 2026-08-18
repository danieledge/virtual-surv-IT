import { defineConfig } from 'vitest/config'

// Separate from vite.config.ts (Vitest's own recommendation - avoids UserConfig type
// conflicts between the two). Only src/lib/*.ts (pure, framework-free logic) is under test
// for v1 - no component/rendering test framework, see the plan's scoped-out note.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/lib/**/*.test.ts'],
  },
})
