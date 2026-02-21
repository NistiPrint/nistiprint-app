import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v2', // Configured in vite.config.js proxy to point to backend
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Important for session cookies
});

// Add cache-busting headers for auth requests
api.interceptors.request.use((config) => {
  if (config.url.includes('/login') || config.url.includes('/logout') || config.url.includes('/current-user')) {
    config.headers['Cache-Control'] = 'no-cache';
    config.headers['Pragma'] = 'no-cache';
  }
  return config;
});

// Response interceptor to handle 401s
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      // If 401, it means the session is invalid.
      // We can let the calling code handle it (like AuthContext)
    }
    return Promise.reject(error);
  }
);

export default api;
