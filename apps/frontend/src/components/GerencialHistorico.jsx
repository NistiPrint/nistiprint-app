import React, { useState, useEffect } from "react";
import axios from "axios";

const GerencialHistorico = () => {
  const [dadosDiarios, setDadosDiarios] = useState([]);
  const [dadosDemanda, setDadosDemanda] = useState([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [demandaId, setDemandaId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Buscar dados gerenciais diários
  const fetchDadosDiarios = async (date = null) => {
    setLoading(true);
    setError("");
    try {
      const response = await axios.get(
        `/api/v2/relatorios/gerenciais/diario${date ? `?data=${date}` : ""}`,
      );
      if (response.data.success) {
        setDadosDiarios(response.data.data);
      } else {
        setError(response.data.error || "Erro desconhecido");
      }
    } catch (err) {
      setError(err.message || "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  };

  // Buscar dados de uma demanda específica
  const fetchDadosDemanda = async (id = null) => {
    setLoading(true);
    setError("");
    try {
      const response = await axios.get(
        `/api/v2/relatorios/gerenciais/demanda${id ? `?demanda_id=${id}` : ""}`,
      );
      if (response.data.success) {
        setDadosDemanda(response.data.data);
      } else {
        setError(response.data.error || "Erro desconhecido");
      }
    } catch (err) {
      setError(err.message || "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  };

  // Carregar dados iniciais
  useEffect(() => {
    fetchDadosDiarios();
  }, []);

  const handleDateChange = (e) => {
    setSelectedDate(e.target.value);
  };

  const handleDemandaIdChange = (e) => {
    setDemandaId(e.target.value);
  };

  const handleSubmitDate = (e) => {
    e.preventDefault();
    fetchDadosDiarios(selectedDate);
  };

  const handleSubmitDemanda = (e) => {
    e.preventDefault();
    if (demandaId) {
      fetchDadosDemanda(parseInt(demandaId));
    }
  };

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-2xl font-bold mb-6">
        Consulta de Dados Gerenciais Históricos
      </h1>

      {/* Filtro por data */}
      <div className="bg-white p-4 rounded-lg shadow-md mb-6">
        <h2 className="text-xl font-semibold mb-4">Filtrar por Data</h2>
        <form onSubmit={handleSubmitDate}>
          <div className="flex items-center space-x-4">
            <input
              type="date"
              value={selectedDate}
              onChange={handleDateChange}
              className="border border-gray-300 rounded px-3 py-2 w-48"
            />
            <button
              type="submit"
              className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"
              disabled={loading}
            >
              Filtrar
            </button>
          </div>
        </form>
      </div>

      {/* Filtro por ID da demanda */}
      <div className="bg-white p-4 rounded-lg shadow-md mb-6">
        <h2 className="text-xl font-semibold mb-4">Filtrar por Demanda</h2>
        <form onSubmit={handleSubmitDemanda}>
          <div className="flex items-center space-x-4">
            <input
              type="number"
              value={demandaId}
              onChange={handleDemandaIdChange}
              placeholder="ID da Demanda"
              className="border border-gray-300 rounded px-3 py-2 w-48"
            />
            <button
              type="submit"
              className="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded"
              disabled={loading}
            >
              Filtrar
            </button>
          </div>
        </form>
      </div>

      {/* Exibição de erros */}
      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-6">
          <strong>Erro:</strong> {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center my-6">
          <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
        </div>
      )}

      {/* Resultados Diários */}
      <div className="bg-white p-4 rounded-lg shadow-md mb-6">
        <h2 className="text-xl font-semibold mb-4">Dados Gerenciais Diários</h2>
        {dadosDiarios.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full bg-white">
              <thead>
                <tr className="bg-gray-100 text-gray-600 text-sm leading-normal">
                  <th className="py-3 px-6 text-left">Data Base</th>
                  <th className="py-3 px-6 text-left">Demandas Criadas</th>
                  <th className="py-3 px-6 text-left">Demandas Concluídas</th>
                  <th className="py-3 px-6 text-left">Itens Demandados</th>
                  <th className="py-3 px-6 text-left">Itens Coletados</th>
                  <th className="py-3 px-6 text-left">Demandas Coletadas</th>
                </tr>
              </thead>
              <tbody className="text-gray-600 text-sm">
                {dadosDiarios.map((item, index) => (
                  <tr
                    key={index}
                    className="border-b border-gray-200 hover:bg-gray-50"
                  >
                    <td className="py-3 px-6">{item.data_base}</td>
                    <td className="py-3 px-6">{item.total_demandas_criadas}</td>
                    <td className="py-3 px-6">
                      {item.total_demandas_concluidas}
                    </td>
                    <td className="py-3 px-6">{item.total_itens_demandados}</td>
                    <td className="py-3 px-6">{item.total_itens_coletados}</td>
                    <td className="py-3 px-6">
                      {item.total_demandas_coletadas}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>Nenhum dado encontrado.</p>
        )}
      </div>

      {/* Resultados por Demanda */}
      <div className="bg-white p-4 rounded-lg shadow-md">
        <h2 className="text-xl font-semibold mb-4">
          Dados Gerenciais por Demanda
        </h2>
        {dadosDemanda.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full bg-white">
              <thead>
                <tr className="bg-gray-100 text-gray-600 text-sm leading-normal">
                  <th className="py-3 px-6 text-left">ID</th>
                  <th className="py-3 px-6 text-left">Descrição</th>
                  <th className="py-3 px-6 text-left">Status</th>
                  <th className="py-3 px-6 text-left">Canal de Venda</th>
                  <th className="py-3 px-6 text-left">Total Itens</th>
                  <th className="py-3 px-6 text-left">Capas Produzidas</th>
                  <th className="py-3 px-6 text-left">Miolo Prontos</th>
                  <th className="py-3 px-6 text-left">Total Coletado</th>
                </tr>
              </thead>
              <tbody className="text-gray-600 text-sm">
                {dadosDemanda.map((item, index) => (
                  <tr
                    key={index}
                    className="border-b border-gray-200 hover:bg-gray-50"
                  >
                    <td className="py-3 px-6">{item.demanda_id}</td>
                    <td className="py-3 px-6">{item.descricao}</td>
                    <td className="py-3 px-6">{item.status}</td>
                    <td className="py-3 px-6">{item.canal_venda_nome}</td>
                    <td className="py-3 px-6">{item.total_itens}</td>
                    <td className="py-3 px-6">{item.total_capas_produzidas}</td>
                    <td className="py-3 px-6">{item.total_miolos_prontos}</td>
                    <td className="py-3 px-6">{item.total_coletado}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>Nenhum dado de demanda encontrado.</p>
        )}
      </div>
    </div>
  );
};

export default GerencialHistorico;
