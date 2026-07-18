import { registerSW } from 'virtual:pwa-register'

export function registerPlayTrackServiceWorker(): void {
  registerSW({ immediate: true })
}
