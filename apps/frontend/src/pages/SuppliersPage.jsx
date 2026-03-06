// frontend/src/pages/SuppliersPage.jsx
import React, { useState, useEffect } from 'react';
import './SuppliersPage.css'; // Assumindo que haverá um CSS específico

// Placeholder para o serviço de API (será implementado/ajustado depois)
// import { fetchSuppliers, createSupplier, updateSupplier } from '../services/supplierService';

function SuppliersPage() {
    const [suppliers, setSuppliers] = useState([]);
    const [formData, setFormData] = useState({
        id: null,
        nome: '',
        cnpj: '',
        contato_principal: '',
        informacoes_contato: {}, // Campo JSON para telefone, email, endereço
        categoria: '',
        classificacao: 0, // Assumindo uma classificação numérica (ex: 1-5)
        ativo: true,
    });
    const [isEditing, setIsEditing] = useState(false);

    // --- Funções para buscar/salvar dados (placeholders) ---
    const loadSuppliers = async () => {
        // Simulação de carregamento de dados
        console.log("Carregando fornecedores...");
        // try {
        //     const data = await fetchSuppliers();
        //     setSuppliers(data);
        // } catch (error) {
        //     console.error("Erro ao carregar fornecedores:", error);
        // }
    };

    const handleInputChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value
        }));
    };

    const handleInformacoesContatoChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({
            ...prev,
            informacoes_contato: {
                ...prev.informacoes_contato,
                [name]: value
            }
        }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        console.log("Enviando dados do fornecedor:", formData);
        // Lógica para criar ou atualizar fornecedor
        // try {
        //     if (isEditing) {
        //         await updateSupplier(formData.id, formData);
        //     } else {
        //         await createSupplier(formData);
        //     }
        //     setFormData({ ...formData, id: null, nome: '', cnpj: '', contato_principal: '', informacoes_contato: {}, categoria: '', classificacao: 0, ativo: true });
        //     setIsEditing(false);
        //     loadSuppliers(); // Recarregar a lista após salvar
        // } catch (error) {
        //     console.error("Erro ao salvar fornecedor:", error);
        // }
    };

    const handleEdit = (supplier) => {
        setFormData(supplier);
        setIsEditing(true);
    };

    const handleCancelEdit = () => {
        setFormData({ ...formData, id: null, nome: '', cnpj: '', contato_principal: '', informacoes_contato: {}, categoria: '', classificacao: 0, ativo: true });
        setIsEditing(false);
    };

    // Simular o carregamento inicial de dados
    useEffect(() => {
        loadSuppliers();
    }, []);

    return (
        <div className="suppliers-container">
            <h1>Cadastro de Fornecedores</h1>

            <div className="supplier-form-section">
                <h2>{isEditing ? 'Editar Fornecedor' : 'Novo Fornecedor'}</h2>
                <form onSubmit={handleSubmit}>
                    <input
                        type="text"
                        name="nome"
                        placeholder="Nome do Fornecedor"
                        value={formData.nome}
                        onChange={handleInputChange}
                        required
                    />
                    <input
                        type="text"
                        name="cnpj"
                        placeholder="CNPJ (ex: XX.XXX.XXX/XXXX-XX)"
                        value={formData.cnpj}
                        onChange={handleInputChange}
                        // Adicionar máscara se necessário
                    />
                    <input
                        type="text"
                        name="contato_principal"
                        placeholder="Contato Principal (Nome)"
                        value={formData.contato_principal}
                        onChange={handleInputChange}
                    />
                    {/* Campos para Informações de Contato (JSON) */}
                    <div className="contact-info-fields">
                        <h3>Informações de Contato</h3>
                        <input
                            type="email"
                            name="email"
                            placeholder="Email"
                            value={formData.informacoes_contato.email || ''}
                            onChange={handleInformacoesContatoChange}
                        />
                        <input
                            type="tel"
                            name="telefone"
                            placeholder="Telefone"
                            value={formData.informacoes_contato.telefone || ''}
                            onChange={handleInformacoesContatoChange}
                        />
                        <input
                            type="text"
                            name="endereco"
                            placeholder="Endereço"
                            value={formData.informacoes_contato.endereco || ''}
                            onChange={handleInformacoesContatoChange}
                        />
                    </div>
                    <input
                        type="text"
                        name="categoria"
                        placeholder="Categoria (ex: Matéria-prima, Serviços)"
                        value={formData.categoria}
                        onChange={handleInputChange}
                    />
                    <label>
                        Classificação (1-5):
                        <input
                            type="number"
                            name="classificacao"
                            min="0"
                            max="5"
                            value={formData.classificacao}
                            onChange={handleInputChange}
                        />
                    </label>
                    <label>
                        Ativo:
                        <input
                            type="checkbox"
                            name="ativo"
                            checked={formData.ativo}
                            onChange={handleInputChange}
                        />
                    </label>

                    <div className="form-actions">
                        <button type="submit">{isEditing ? 'Salvar Alterações' : 'Adicionar Fornecedor'}</button>
                        {isEditing && <button type="button" onClick={handleCancelEdit}>Cancelar</button>}
                    </div>
                </form>
            </div>

            {/* Placeholder para a lista de fornecedores */}
            <div className="supplier-list-section">
                <h2>Fornecedores Cadastrados</h2>
                {suppliers.length === 0 ? (
                    <p>Nenhum fornecedor cadastrado ainda.</p>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>Nome</th>
                                <th>CNPJ</th>
                                <th>Categoria</th>
                                <th>Classificação</th>
                                <th>Status</th>
                                <th>Ações</th>
                            </tr>
                        </thead>
                        <tbody>
                            {suppliers.map(supplier => (
                                <tr key={supplier.id}>
                                    <td>{supplier.nome}</td>
                                    <td>{supplier.cnpj}</td>
                                    <td>{supplier.categoria}</td>
                                    <td>{supplier.classificacao}</td>
                                    <td>{supplier.ativo ? 'Ativo' : 'Inativo'}</td>
                                    <td>
                                        <button onClick={() => handleEdit(supplier)}>Editar</button>
                                        {/* Adicionar botão de excluir se necessário */}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}

export default SuppliersPage;
