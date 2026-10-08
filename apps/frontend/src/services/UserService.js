import api from './api';

const UserService = {
  // Autenticação
  login: async (credentials) => {
    const response = await api.post('/login', credentials);
    return response.data;
  },

  logout: async () => {
    const response = await api.post('/logout');
    return response.data;
  },

  getCurrentUser: async () => {
    try {
      const response = await api.get('/current-user');
      if (response.data && response.data.usuario) {
        return response.data.usuario;
      }
      return null;
    } catch (error) {
      throw error;
    }
  },

  updateProfile: async (data) => {
    const response = await api.patch('/current-user', data);
    return response.data.usuario;
  },

  changePassword: async (data) => {
    const response = await api.post('/change-password', data);
    return response.data.usuario;
  },

  // Gerenciamento de usuários
  getAll: async () => {
    const response = await api.get('/usuarios-setores/usuario');
    return response.data.usuarios;
  },

  getById: async (id) => {
    const response = await api.get(`/usuarios-setores/usuario/${id}`);
    return response.data.usuario;
  },

  create: async (userData) => {
    const response = await api.post('/usuarios-setores/usuario', userData);
    return response.data;
  },

  update: async (id, userData) => {
    const response = await api.put(`/usuarios-setores/usuario/${id}`, userData);
    return response.data.usuario;
  },

  delete: async (id) => {
    const response = await api.delete(`/usuarios-setores/usuario/${id}`);
    return response.data;
  },

  provisionAccess: async (id, senhaInicial) => {
    const response = await api.post(`/usuarios-setores/usuario/${id}/access`, { senha_inicial: senhaInicial });
    return response.data.usuario;
  },
};

export default UserService;
