import { beforeEach, expect, it, vi } from 'vitest'

const registerSW = vi.hoisted(() => vi.fn())

vi.mock('virtual:pwa-register', () => ({ registerSW }))

import { registerPlayTrackServiceWorker } from './pwa'

beforeEach(() => registerSW.mockClear())

it('registers automatic service-worker updates immediately', () => {
  registerPlayTrackServiceWorker()

  expect(registerSW).toHaveBeenCalledWith({ immediate: true })
})
