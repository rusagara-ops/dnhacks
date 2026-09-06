import { defineConfig } from 'vite';

// Dev only. The demo dashboard and the React app both call the coordinator on the
// same origin (`/api`). Point that at a coordinator running elsewhere on the LAN so
// the UI can be developed without a local backend and database.
const coordinator = process.env.COORDINATOR_URL || 'http://127.0.0.1:8000';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    proxy: { '/api': { target: coordinator, changeOrigin: true } },
  },
});
