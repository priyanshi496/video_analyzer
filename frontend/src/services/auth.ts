import { api } from './api';

export const authService = {
  async login(email: string, password: string) {
    const formData = new URLSearchParams();
    formData.append('username', email); // OAuth2 form uses 'username'
    formData.append('password', password);
    
    const response = await api.post('/auth/token', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    });
    return response.data;
  },

  async register(email: string, password: string) {
    const response = await api.post('/auth/register', { email, password });
    return response.data;
  },

  async getMe() {
    const response = await api.get('/auth/me');
    return response.data;
  },

  logout() {
    localStorage.removeItem('token');
    window.location.href = '/login';
  }
};
