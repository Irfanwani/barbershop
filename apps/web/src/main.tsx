import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import './styles.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('No #root element — the HTML entry point is missing.');
}

/*
 * `base` stays relative for portable builds, but GitHub Pages needs the router
 * to know it is mounted under `/barbershop`. The deploy workflow sets
 * `VITE_BASE_PATH`; everywhere else BASE_URL is `./` and the basename is `/`.
 */
const baseUrl = import.meta.env.BASE_URL;
const basename = baseUrl === './' ? '/' : baseUrl.replace(/\/$/, '') || '/';

createRoot(container).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
