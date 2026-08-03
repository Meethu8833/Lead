import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import QueryProvider from './components/providers/QueryProvider';
import ThemeProvider from './components/providers/ThemeProvider';
import ToastProvider from './components/providers/ToastProvider';
import App from './App';
import './styles/index.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('Failed to find the root element');
}

const root = createRoot(container);

root.render(
  <React.StrictMode>
    <QueryProvider>
      <ThemeProvider>
        <BrowserRouter>
          <App />
          <ToastProvider />
        </BrowserRouter>
      </ThemeProvider>
    </QueryProvider>
  </React.StrictMode>
);
