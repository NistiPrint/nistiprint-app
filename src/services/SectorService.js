import api from './api';

const SectorService = {
  getAll: async () => {
    const response = await api.get('/usuarios-setores/setor');
    return response.data.setores;
  },

  getById: async (id) => {
    const response = await api.get(`/usuarios-setores/setor/${id}`);
    return response.data.setor;
  },

  create: async (sectorData) => {
    const response = await api.post('/usuarios-setores/setor', sectorData);
    return response.data.setor;
  },

  update: async (id, sectorData) => {
    const response = await api.put(`/usuarios-setores/setor/${id}`, sectorData);
    return response.data.setor;
  },

  delete: async (id) => {
    const response = await api.delete(`/usuarios-setores/setor/${id}`);
    return response.data;
  },

  // Permission Methods
  getResources: async () => {
    const response = await api.get('/usuarios-setores/recursos');
    return response.data.recursos;
  },

  getPermissions: async (sectorId) => {
    const response = await api.get(`/usuarios-setores/setor/${sectorId}/permissoes`);
    return response.data.permissoes;
  },

  updatePermission: async (sectorId, permissionData) => {
    // permissionData: { recurso: 'nome', ler: bool, criar: bool, editar: bool, excluir: bool }
    const response = await api.post(`/usuarios-setores/setor/${sectorId}/permissoes`, permissionData);
    return response.data.permissao;
  }
};

export default SectorService;
