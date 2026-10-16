# ConfigLabs

Free network tools for engineers — **https://configlabs.online**

- **Config Builder** — generate H3C Comware and Cisco IOS / IOS-XE / NX-OS configs from a form (18 templates).
- **WiFi Planner** (beta) — floor-plan heatmaps (signal, SINR, coverage), field calibration and Word reports.

## Stack
Static HTML/JS frontend + a small Flask API (`ConfigLab.py`) on Vercel, Neon PostgreSQL for optional Google-login saved configs.
WiFi Planner projects stay in the browser (IndexedDB).

## Versions
The site version lives in one place: `site.js` (`window.CL`). Pages and the API (`APP_VERSION` in `ConfigLab.py`) follow it.

## Environment variables
`DATABASE_URL`, `SESSION_SECRET`, `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

## License
[MIT](LICENSE) © 2026 Naufal Budiman. H3C, Comware and Cisco are trademarks of their owners; this project is independent.
