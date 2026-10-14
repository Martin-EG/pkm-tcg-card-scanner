import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

// Tell React this is a test environment, so state updates are wrapped in act().
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
  localStorage.clear()
})
