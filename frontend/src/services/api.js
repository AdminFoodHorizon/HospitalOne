import axios from 'axios';

export const api = axios.create({
  baseURL: process.env.REACT_APP_API_BASE_URL || '',
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
  headers: { 'Content-Type': 'application/json' },
});

function csrfCookie() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}

api.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase();
  if (!['get', 'head', 'options'].includes(method)) {
    const token = csrfCookie();
    if (token) config.headers['X-CSRFToken'] = token;
  }
  return config;
});

export const hospitalPath = (slug, route) =>
  `/api/hospital/${encodeURIComponent(slug)}/${route}/`;

export const csrf = () => api.get('/api/hospital/csrf/');

export const hospitalPost = (slug, route, data = {}, config = {}) =>
  api.post(hospitalPath(slug, route), data, config);

// Accept an optional Axios config so returning-patient search can send ?q=...
export const hospitalGet = (slug, route, config = {}) =>
  api.get(hospitalPath(slug, route), config);

export function errorText(error) {
  const data = error?.response?.data;
  if (typeof data?.detail === 'string') return data.detail;
  if (typeof data?.error === 'string') return data.error;
  if (typeof data?.message === 'string') return data.message;
  if (data && typeof data === 'object') {
    const first = Object.values(data).find((v) => typeof v === 'string' || Array.isArray(v));
    if (first) return Array.isArray(first) ? first.join(', ') : first;
  }
  return error?.message || 'Something went wrong. Please try again.';
}
