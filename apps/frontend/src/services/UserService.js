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
    return response.data.usuario;
  },

  update: async (id, userData) => {
    const response = await api.put(`/usuarios-setores/usuario/${id}`, userData);
    return response.data.usuario;
  },

  delete: async (id) => {
    const response = await api.delete(`/usuarios-setores/usuario/${id}`);
    return response.data;
  }
};

export default UserService;
