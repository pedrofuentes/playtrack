import { createRoot } from 'react-dom/client'

import App from './App'
import './styles.css'
import { registerPlayTrackServiceWorker } from './pwa'

registerPlayTrackServiceWorker()

createRoot(document.getElementById('root')!).render(<App />)
