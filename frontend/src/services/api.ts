import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add the auth token to headers
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor to handle errors gracefully
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;

    // Handle auth expiry
    if (status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      return Promise.reject(error);
    }

    // Sanitize error messages — never leak raw server details
    let userMessage = 'Something went wrong. Please try again.';
    if (status === 404) {
      userMessage = 'The requested resource was not found.';
    } else if (status === 400) {
      // 400s often have useful, safe user-facing messages (e.g. "wrong status")
      userMessage = error.response?.data?.detail || 'Invalid request.';
    } else if (status === 413) {
      userMessage = 'File is too large to upload.';
    } else if (status >= 500) {
      userMessage = 'Something went wrong on our end. Please try again later.';
    } else if (!error.response) {
      // Network error — backend is completely unreachable
      userMessage = 'Cannot reach the server. Please check your connection.';
    }

    // Attach the clean message as a new property so callers can use it
    error.userMessage = userMessage;
    return Promise.reject(error);
  }
);
