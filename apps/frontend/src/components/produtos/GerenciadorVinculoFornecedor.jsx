// frontend/src/components/produtos/GerenciadorVinculoFornecedor.jsx
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import FornecedorInsumoService from '@/services/FornecedorInsumoService';
import FornecedorService from '@/services/FornecedorService';
import { Pencil, PlusCircle, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useFormContext } from 'react-hook-form';
import { toast } from 'sonner';

// Componente para o modal de cadastro rápido de fornecedor
function FornecedorQuickAddModal({ isOpen, onClose, onSupplierCreated }) {
  const [formState, setFormState] = useState({
    nome: '',
    cnpj: '',
    contato_principal: '',
    informacoes_contato: {},
    categoria: '',
    classificacao: 0,
  });

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormState(prev => ({ ...prev, [name]: value }));
  };

  const handleInformacoesContatoChange = (e) => {
    const { name, value } = e.target;
    setFormState(prev => ({
      ...prev,
      informacoes_contato: {
        ...prev.informacoes_contato,
        [name]: value
      }
    }));
  };

  const handleSubmit = async () => {
    if (!formState.nome || !formState.cnpj) {
      toast.error('Nome e CNPJ são obrigatórios para cadastrar um fornecedor.');
      return;
    }
    try {
      const newSupplier = await FornecedorService.create(formState);
      toast.success(`Fornecedor "${newSupplier.nome}" criado com sucesso!`);
      onSupplierCreated(newSupplier); // Passa o novo fornecedor para o modal pai
      setFormState({ nome: '', cnpj: '', contato_principal: '', informacoes_contato: {}, categoria: '', classificacao: 0 }); // Limpa o formulário
      onClose(); // Fecha o modal
    } catch (error) {
      console.error("Erro ao criar fornecedor:", error);
      toast.error(`Erro ao criar fornecedor: ${error.response?.data?.error || error.message}`);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white p-6 rounded-lg shadow-lg max-w-md w-full">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">Cadastrar Novo Fornecedor</h3>
          <Button variant="ghost" size="icon" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        <div className="space-y-4">
          <Input
            placeholder="Nome do Fornecedor"
            value={formState.nome}
            onChange={handleInputChange}
            name="nome"
            required
          />
          <Input
            placeholder="CNPJ (XX.XXX.XXX/XXXX-XX)"
            value={formState.cnpj}
            onChange={handleInputChange}
            name="cnpj"
          />
          <Input
            placeholder="Contato Principal"
            value={formState.contato_principal}
            onChange={handleInputChange}
            name="contato_principal"
          />
          <div className="space-y-2">
            <Label>Informações de Contato</Label>
            <Input
              placeholder="Email"
              type="email"
              value={formState.informacoes_contato.email || ''}
              onChange={handleInformacoesContatoChange}
              name="email"
            />
            <Input
              placeholder="Telefone"
              type="tel"
              value={formState.informacoes_contato.telefone || ''}
              onChange={handleInformacoesContatoChange}
              name="telefone"
            />
            <Input
              placeholder="Endereço"
              value={formState.informacoes_contato.endereco || ''}
              onChange={handleInformacoesContatoChange}
              name="endereco"
            />
          </div>
          <Input
            placeholder="Categoria"
            value={formState.categoria}
            onChange={handleInputChange}
            name="categoria"
          />
          <Input
            type="number"
            placeholder="Classificação (1-5)"
            min="0"
            max="5"
            value={formState.classificacao}
            onChange={handleInputChange}
            name="classificacao"
          />
        </div>
        <div className="mt-6 flex justify-end">
          <Button onClick={handleSubmit}>Adicionar Fornecedor</Button>
        </div>
      </div>
    </div>
  );
}


function GerenciadorVinculoFornecedor({ productId, productForm }) {
  const [fornecedores, setFornecedores] = useState([]);
  const [vinculos, setVinculos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isQuickAddModalOpen, setIsQuickAddModalOpen] = useState(false);

  // Form fields from the main product form context
  const { watch, setValue, resetField } = useFormContext();
  const currentFormato = watch('formato');

  // Fetch all suppliers to populate the dropdown
  const loadFornecedores = useCallback(async () => {
    try {
      const data = await FornecedorService.getAll();
      setFornecedores(data);
    } catch (error) {
      console.error("Erro ao carregar fornecedores:", error);
      toast.error("Erro ao carregar a lista de fornecedores.");
    }
  }, []);

  // Fetch existing links for the current product
  const loadVinculos = useCallback(async () => {
    if (!productId) {
      setVinculos([]);
      setLoading(false);
      return;
    }
    try {
      const data = await FornecedorInsumoService.getLinksForProduct(productId);
      // Map data to fit the expected format for the form
      const formattedLinks = data.map(link => ({
        id: link.id, // ID da ligação fornecedor_insumo
        fornecedor_id: link.fornecedor_id,
        fornecedor_nome: link.fornecedor_nome, // Assuming backend provides this
        lead_time_dias: link.lead_time_dias,
        moq: link.moq,
        preco_ultima_compra: link.preco_ultima_compra,
        codigo_no_fornecedor: link.codigo_no_fornecedor,
        unidade_compra: link.unidade_compra,
      }));
      setVinculos(formattedLinks);
      // Update the main form with initial data if product is being edited
      productForm.setValue('fornecedor_insumos', formattedLinks);
    } catch (error) {
      console.error("Erro ao carregar vínculos de fornecedor:", error);
      toast.error("Erro ao carregar vínculos de fornecedor.");
    } finally {
      setLoading(false);
    }
  }, [productId, productForm.setValue]);

  // Initialize loading state
  useEffect(() => {
    setLoading(true);
    loadFornecedores();
    loadVinculos();
  }, [loadFornecedores, loadVinculos]);

  const handleAddLink = () => {
    const newLink = {
      id: null, // null indicates new link
      fornecedor_id: '',
      fornecedor_nome: '', // Will be filled on selection
      lead_time_dias: 0,
      moq: 0,
      preco_ultima_compra: 0,
      codigo_no_fornecedor: '',
      unidade_compra: '',
    };
    setVinculos([...vinculos, newLink]);
  };

  const handleRemoveLink = (indexToRemove) => {
    const updatedVinculos = vinculos.filter((_, index) => index !== indexToRemove);
    setVinculos(updatedVinculos);
    // Update the main form's state
    productForm.setValue('fornecedor_insumos', updatedVinculos);
  };

  const handleLinkInputChange = (index, field, value) => {
    const updatedVinculos = [...vinculos];
    updatedVinculos[index] = { ...updatedVinculos[index], [field]: value };
    setVinculos(updatedVinculos);
    // Update the main form's state
    productForm.setValue('fornecedor_insumos', updatedVinculos);
  };

  const handleSelectFornecedor = (index, selectedFornecedorId) => {
    const selectedFornecedor = fornecedores.find(f => String(f.id) === selectedFornecedorId);
    if (selectedFornecedor) {
      const updatedVinculos = [...vinculos];
      updatedVinculos[index] = {
        ...updatedVinculos[index],
        fornecedor_id: selectedFornecedorId,
        fornecedor_nome: selectedFornecedor.nome,
        // Potentially pre-fill other fields if available on supplier, like default unit_compra
      };
      setVinculos(updatedVinculos);
      productForm.setValue('fornecedor_insumos', updatedVinculos);
    }
  };

  const handleSaveLinks = async () => {
    // Filter out links that are intended to be new but don't have a selected supplier
    const validLinks = vinculos.filter(link => link.fornecedor_id);
    
    // Validate required fields for each link (e.g., lead_time_dias, moq)
    for (const link of validLinks) {
        if (link.lead_time_dias === undefined || link.moq === undefined || link.preco_ultima_compra === undefined) {
            toast.error("Por favor, preencha todos os campos obrigatórios (Lead Time, MOQ, Preço) para cada vínculo de fornecedor.");
            return;
        }
    }

    try {
      // The backend will need to handle creating new links and updating existing ones
      // For simplicity here, we assume a batch update/create endpoint or individual calls
      // A more robust solution might involve tracking new/updated/deleted links
      
      // Assuming productForm.productId exists or is passed down
      const productIdentifier = productId || productForm.getValues('id'); // Use form's ID if editing

      if (!productIdentifier) {
        toast.error("Não foi possível identificar o produto para salvar os vínculos.");
        return;
      }

      // Placeholder: Ideally, this would be a more sophisticated API call
      // e.g., ProductService.updateSupplierLinks(productIdentifier, validLinks)
      // For now, we update the main product form data, assuming it will be saved on product save
      productForm.setValue('fornecedor_insumos', validLinks);
      toast.info("Vínculos de fornecedor atualizados no formulário principal. Salve o produto para confirmar.");

      // If you have a dedicated service for FornecedorInsumo:
      // await FornecedorInsumoService.saveForProduct(productIdentifier, validLinks);
      // toast.success("Vínculos de fornecedor salvos com sucesso!");

    } catch (error) {
      console.error("Erro ao salvar vínculos:", error);
      toast.error(`Erro ao salvar vínculos de fornecedor: ${error.response?.data?.error || error.message}`);
    }
  };

  // Handle quick add supplier creation from modal
  const handleQuickAddSupplier = (newSupplier) => {
    // Add the newly created supplier to the local list and select it
    setFornecedores([...fornecedores, newSupplier]);
    handleSelectFornecedor(vinculos.findIndex(v => v.id === null), String(newSupplier.id)); // Select the new supplier in the first empty link
  };

  if (loading) return <div className="flex justify-center py-10"><Loader2 className="h-8 w-8 animate-spin" /></div>;

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Fornecedores e Vínculos</CardTitle>
        <div className="flex justify-end">
          <Button onClick={() => setIsQuickAddModalOpen(true)} variant="secondary" size="sm">
            <PlusCircle className="h-4 w-4 mr-2" /> Cadastrar Novo Fornecedor
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {/* Form for adding/editing links */}
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-4">Vincular Fornecedor ao Produto</h3>
          {vinculos.map((link, index) => (
            <div key={link.id || index} className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-4 p-4 border rounded-lg shadow-sm items-center">
              <div className="col-span-1 lg:col-span-2">
                <Label htmlFor={`fornecedor-${index}`}>Fornecedor *</Label>
                <Select
                  onValueChange={(value) => handleSelectFornecedor(index, value)}
                  value={link.fornecedor_id ? String(link.fornecedor_id) : ''}
                  disabled={!fornecedores.length}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={fornecedores.length ? "Selecione um fornecedor" : "Carregando fornecedores..."} />
                  </SelectTrigger>
                  <SelectContent>
                    {fornecedores.map(f => (
                      <SelectItem key={f.id} value={String(f.id)}>{f.nome} ({f.cnpj})</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Input
                type="number"
                placeholder="Lead Time (dias)"
                value={link.lead_time_dias}
                onChange={(e) => handleLinkInputChange(index, 'lead_time_dias', parseInt(e.target.value) || 0)}
                className="col-span-1"
              />
              <Input
                type="number"
                placeholder="MOQ (Lote Mínimo)"
                value={link.moq}
                onChange={(e) => handleLinkInputChange(index, 'moq', parseFloat(e.target.value) || 0)}
                className="col-span-1"
              />
              <Input
                type="number"
                placeholder="Preço Última Compra"
                step="0.01"
                value={link.preco_ultima_compra}
                onChange={(e) => handleLinkInputChange(index, 'preco_ultima_compra', parseFloat(e.target.value) || 0)}
                className="col-span-1"
              />
              <Input
                placeholder="Código no Fornecedor"
                value={link.codigo_no_fornecedor}
                onChange={(e) => handleLinkInputChange(index, 'codigo_no_fornecedor', e.target.value)}
                className="col-span-1"
              />
              <Input
                placeholder="Unidade de Compra (ex: KG, UN)"
                value={link.unidade_compra}
                onChange={(e) => handleLinkInputChange(index, 'unidade_compra', e.target.value)}
                className="col-span-1"
              />

              <div className="col-span-1 lg:col-span-4 flex items-center justify-end gap-2">
                {link.id && (
                  <Button variant="outline" size="sm" className="text-blue-600 hover:text-blue-800" onClick={() => { /* TODO: Implement edit link logic if needed */ }}>
                    <Pencil className="h-3 w-3 mr-1" /> Editar
                  </Button>
                )}
                <Button variant="outline" size="sm" className="text-red-600 hover:text-red-800" onClick={() => handleRemoveLink(index)}>
                  <Trash2 className="h-4 w-4" /> Remover
                </Button>
              </div>
            </div>
          ))}
          <Button onClick={handleAddLink} variant="outline" className="w-full">
            <PlusCircle className="h-4 w-4 mr-2" /> Adicionar Novo Vínculo
          </Button>
        </div>

        {/* Save button for links */}
        <div className="mt-6 pt-4 border-t">
          <Button onClick={handleSaveLinks} className="w-full">Salvar Vínculos de Fornecedor</Button>
        </div>

        {/* Quick Add Modal */}
        <FornecedorQuickAddModal
          isOpen={isQuickAddModalOpen}
          onClose={() => setIsQuickAddModalOpen(false)}
          onSupplierCreated={handleQuickAddSupplier}
        />
      </CardContent>
    </Card>
  );
}

export default GerenciadorVinculoFornecedor;
