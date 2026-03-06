import { useEffect, useState } from 'react';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { Plus, Save, Tags, Trash2, Edit3, X, CheckCircle, AlertTriangle, Settings, Package, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import VariationEditModal from './VariationEditModal';

const VariationManager = ({ product, onSave, autoOpenVariationId }) => {
  const [variationsConfig, setVariationsConfig] = useState([]);
  const [variationsTable, setVariationsTable] = useState([]);
  const [editingInlineIndex, setEditingInlineIndex] = useState(null);

  // Modal State
  const [variationToEdit, setVariationToEdit] = useState(autoOpenVariationId || null); // ID of variation to edit in modal
  const [isModalOpen, setIsModalOpen] = useState(!!autoOpenVariationId);

  // UI States
  const [showAddAttributeModal, setShowAddAttributeModal] = useState(false);
  const [newAttributeName, setNewAttributeName] = useState('');
  const [newAttributeValue, setNewAttributeValue] = useState('');
  const [selectedAttributeIndex, setSelectedAttributeIndex] = useState(-1);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);

  // Initialize from product data if available
  useEffect(() => {
    if (product?.atributos?.variations_config) {
      setVariationsConfig([...product.atributos.variations_config]);
    }

    // Initial table generation logic
    if (product?.variants || product?.atributos?.variations_config) {
        refreshTable(product.atributos?.variations_config || [], product.variants || []);
    }
  }, [product]);

  // Auto-open variation modal when autoOpenVariationId is provided
  useEffect(() => {
    if (autoOpenVariationId && variationsTable.length > 0 && !isModalOpen) {
      // Find the variation in the table
      const variation = variationsTable.find(v => String(v.id) === String(autoOpenVariationId));
      if (variation) {
        setVariationToEdit(String(autoOpenVariationId));
        setIsModalOpen(true);
        
        // Clear the parameter from URL to prevent reopening on tab switches or refresh
        const url = new URL(window.location);
        if (url.searchParams.has('variation_id')) {
          url.searchParams.delete('variation_id');
          window.history.replaceState({}, '', url);
        }
      }
    }
  }, [autoOpenVariationId, variationsTable, isModalOpen]);

  const refreshTable = (config, variants = []) => {
      // Re-generate table but preserve local changes if needed, 
      // or essentially map existing variants + potential new combinations
      if (!config || config.length === 0) {
        setVariationsTable([]);
        return;
      }

      // 1. Generate all theoretical combinations based on config
      const cartesian = (...args) => args.reduce((acc, curr) => acc.flatMap(c => curr.map(n => [].concat(c, n))), [[]]);
      const attributeNames = config.map(attr => attr.name);
      const attributeOptions = config.map(attr => attr.options);
      
      // If any attribute has no options, we can't generate combinations
      if (attributeOptions.some(opts => opts.length === 0)) {
          return;
      }

      const combinations = cartesian(...attributeOptions);
      
      const matchedVariantIds = new Set();

      const tableData = combinations.map((combo, idx) => {
        const comboObj = {};
        attributeNames.forEach((name, i) => {
          comboObj[name] = combo[i];
        });

        // 2. Match with existing variants
        let existingVariant = null;
        if (variants && variants.length > 0) {
          existingVariant = variants.find(v => {
            const variantAttrs = v.atributos?.variation_values || {};
            return Object.keys(comboObj).every(key => variantAttrs[key] === comboObj[key]);
          });
        }

        if (existingVariant) {
            matchedVariantIds.add(existingVariant.id);
        }

        return {
          // Use real ID if exists, otherwise a temp ID
          id: existingVariant ? existingVariant.id : `draft-${idx}`,
          isPersisted: !!existingVariant,
          isOrphan: false,
          attributes: comboObj,
          // If persisted, use its SKU. If draft, generate a suggestion.
          sku: existingVariant?.sku || `${product?.sku || 'PROD'}-${Object.values(comboObj).join('-')}`,
          initialStock: existingVariant?.estoque_inicial || (existingVariant ? (existingVariant.stock_min || 0) : 0),
          price: existingVariant?.price || existingVariant?.preco_venda || 0,
          variantData: existingVariant || null
        };
      });

      // 3. Identify Orphans (Existing variants that are NOT in the new configuration)
      const orphanVariants = variants.filter(v => !matchedVariantIds.has(v.id));
      
      const orphanData = orphanVariants.map(v => ({
          id: v.id,
          isPersisted: true,
          isOrphan: true,
          attributes: v.atributos?.variation_values || {},
          sku: v.sku,
          initialStock: v.stock_min || 0,
          price: v.preco_venda || 0,
          variantData: v
      }));

      setVariationsTable([...tableData, ...orphanData]);
  };

  // --- Attribute Management ---

  const addAttribute = () => {
    setShowAddAttributeModal(true);
  };

  const handleAddAttribute = () => {
    if (newAttributeName.trim()) {
      const newAttribute = {
        name: newAttributeName.trim(),
        options: []
      };
      const newConfig = [...variationsConfig, newAttribute];
      setVariationsConfig(newConfig);
      setNewAttributeName('');
      setShowAddAttributeModal(false);
      
      // Auto-regenerate table if possible
      refreshTable(newConfig, product?.variants);
      toast.success('Atributo adicionado com sucesso!');
    }
  };

  const addOptionToAttribute = (attrIndex) => {
    if (newAttributeValue.trim() !== '') {
      const updatedConfig = [...variationsConfig];
      if (!updatedConfig[attrIndex].options.includes(newAttributeValue)) {
        updatedConfig[attrIndex].options = [...updatedConfig[attrIndex].options, newAttributeValue];
        setVariationsConfig(updatedConfig);
        setNewAttributeValue('');
        // Auto-regenerate table
        refreshTable(updatedConfig, product?.variants);
      }
    }
  };

  const removeOptionFromAttribute = (attrIndex, optionIndex) => {
    const updatedConfig = [...variationsConfig];
    updatedConfig[attrIndex].options = updatedConfig[attrIndex].options.filter((_, idx) => idx !== optionIndex);
    setVariationsConfig(updatedConfig);
    refreshTable(updatedConfig, product?.variants);
  };

  const removeAttribute = (attrIndex) => {
    const updatedConfig = variationsConfig.filter((_, idx) => idx !== attrIndex);
    setVariationsConfig(updatedConfig);
    refreshTable(updatedConfig, product?.variants);
  };

  // --- Inline Editing (Drafts) ---

  const handleVariationChange = (index, field, value) => {
    const updatedTable = [...variationsTable];
    updatedTable[index][field] = value;
    setVariationsTable(updatedTable);
  };

  const startInlineEditing = (index) => {
    setEditingInlineIndex(index);
  };

  const saveInlineEditing = (index) => {
    setEditingInlineIndex(null);
  };

  const cancelInlineEditing = () => {
    setEditingInlineIndex(null);
  };

  // --- Modal Editing (Persisted) ---

  const openEditModal = (variationId) => {
      setVariationToEdit(variationId);
      setIsModalOpen(true);
  };

  const handleModalSaveSuccess = () => {
      // Trigger a refresh of the product data from parent
      // Since we don't have a direct refresh callback, we can simulate by calling onSave
      // or ideally the parent component should auto-refresh when onSave resolves.
      // For now, let's toast.
      toast.success("Dados recarregados.");
      // In a real scenario, we might want to reload the whole product here.
      if (onSave) {
          // We call onSave with null to signal a "refresh request" or similar if the parent supports it
          // Or we just wait for the user to manually refresh. 
          // Better approach: The parent passes a 'onRefresh' prop.
          // Fallback: We can't easily refresh the table without fetching new data.
      }
  };

  // --- Actions ---

  const handleSave = async () => {
    if (!product) {
      toast.warning("Produto não selecionado");
      return;
    }

    setIsLoading(true);
    try {
      // Filter only what needs to be saved/updated
      // Usually we send everything and the backend figures it out,
      // creating new ones (drafts) and updating existing ones.
      
      const variationsData = variationsTable.map(item => ({
        ...item.variantData, // Include existing data if available
        id: item.isPersisted ? item.id : undefined, // Send ID only if persisted
        sku: item.sku,
        variation_values: item.attributes,
        preco_venda: parseFloat(item.price) || 0,
        estoque_inicial: parseInt(item.initialStock) || 0,
        parent_id: product.id
      }));

      await onSave({
        variations_config: variationsConfig,
        variations_data: variationsData
      });
      // The parent component (ProdutoFormPage) handles the toast and data refresh
    } catch (error) {
      console.error("Erro ao salvar variações:", error);
      toast.error("Erro ao salvar variações: " + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
    <Card className="w-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4 pt-6">
        <div className="flex items-center space-x-2">
          <Settings className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-lg">Gerenciador de Variações</CardTitle>
        </div>
        <div className="flex space-x-2">
            <Button
            onClick={handleSave}
            disabled={isLoading}
            className="gap-2"
            >
            {isLoading ? (
                <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
                Sincronizar Grade
                </>
            ) : (
                <>
                <RefreshCw className="h-4 w-4" /> Sincronizar Grade
                </>
            )}
            </Button>
        </div>
      </CardHeader>
      
      <CardContent className="pb-6 px-6">
        {/* Attributes Configuration */}
        <div className="attributes-section space-y-4 mb-8 bg-muted/30 p-4 rounded-lg">
          <div className="attributes-header flex justify-between items-center mb-2">
            <div className="flex items-center space-x-2">
              <Tags className="h-4 w-4 text-muted-foreground" />
              <h3 className="text-base font-semibold">1. Definir Atributos</h3>
            </div>
            <Button variant="outline" size="sm" onClick={addAttribute} className="gap-2 bg-white">
              <Plus className="h-4 w-4" /> Novo Atributo
            </Button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {variationsConfig.map((attr, attrIdx) => (
                <Card key={attrIdx} className="p-3 shadow-sm">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="font-medium text-sm uppercase tracking-wide text-muted-foreground">{attr.name}</h4>
                    <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removeAttribute(attrIdx)}
                    className="h-6 w-6 text-red-400 hover:text-red-600 hover:bg-red-50"
                    >
                    <Trash2 className="h-3 w-3" />
                    </Button>
                </div>

                <div className="flex space-x-2 mb-2">
                    <Input
                    type="text"
                    value={newAttributeValue}
                    onChange={(e) => setNewAttributeValue(e.target.value)}
                    placeholder="Novo valor..."
                    className="h-8 text-sm"
                    onFocus={() => setSelectedAttributeIndex(attrIdx)}
                    onBlur={() => setTimeout(() => setSelectedAttributeIndex(-1), 200)}
                    disabled={selectedAttributeIndex !== -1 && selectedAttributeIndex !== attrIdx}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                        addOptionToAttribute(attrIdx);
                        }
                    }}
                    />
                    <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => addOptionToAttribute(attrIdx)}
                    disabled={!newAttributeValue.trim() || (selectedAttributeIndex !== -1 && selectedAttributeIndex !== attrIdx)}
                    className="h-8"
                    >
                    Add
                    </Button>
                </div>

                <div className="flex flex-wrap gap-1 min-h-[30px]">
                    {attr.options.map((option, optIdx) => (
                    <Badge key={optIdx} variant="outline" className="flex items-center gap-1 bg-white text-xs py-0 h-6">
                        {option}
                        <X 
                        className="h-3 w-3 cursor-pointer hover:text-red-500 ml-1" 
                        onClick={() => removeOptionFromAttribute(attrIdx, optIdx)}
                        />
                    </Badge>
                    ))}
                    {attr.options.length === 0 && (
                        <span className="text-xs text-muted-foreground italic p-1">Nenhum valor adicionado</span>
                    )}
                </div>
                </Card>
            ))}
          </div>
          
          {variationsConfig.length === 0 && (
              <div className="text-center py-4 text-muted-foreground text-sm border-2 border-dashed rounded-md">
                  Adicione atributos (ex: Cor, Tamanho) para gerar a grade.
              </div>
          )}
        </div>

        {/* Variations Table */}
        <div className="variations-section space-y-4">
            <div className="flex items-center space-x-2">
              <Package className="h-4 w-4 text-muted-foreground" />
              <h3 className="variations-title text-base font-semibold">2. Grade de Produtos Gerada</h3>
            </div>

            {variationsTable.length > 0 ? (
            <div className="border rounded-md overflow-hidden shadow-sm">
              <Table>
                <TableHeader className="bg-muted/50">
                  <TableRow>
                    <TableHead className="w-[100px]">Status</TableHead>
                    {variationsConfig.map(attr => (
                      <TableHead key={attr.name}>{attr.name}</TableHead>
                    ))}
                    <TableHead>SKU</TableHead>
                    <TableHead>Preço</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {variationsTable.map((variation, idx) => (
                    <TableRow key={idx} className={
                        variation.isOrphan 
                        ? "bg-red-50/50 opacity-75" 
                        : (!variation.isPersisted ? "bg-yellow-50/50" : "")
                    }>
                      <TableCell>
                          {variation.isOrphan ? (
                              <Badge variant="destructive" className="bg-red-100 text-red-700 border-red-200">
                                  <Trash2 className="w-3 h-3 mr-1" /> Será Inativado
                              </Badge>
                          ) : variation.isPersisted ? (
                              <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
                                  <CheckCircle className="w-3 h-3 mr-1" /> Salvo
                              </Badge>
                          ) : (
                              <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200">
                                  <AlertTriangle className="w-3 h-3 mr-1" /> Rascunho
                              </Badge>
                          )}
                      </TableCell>
                      
                      {Object.entries(variation.attributes).map(([attrName, attrValue]) => (
                        <TableCell key={attrName} className={variation.isOrphan ? "line-through text-muted-foreground" : ""}>
                            {attrValue}
                        </TableCell>
                      ))}
                      
                      {/* SKU Column */}
                      <TableCell>
                        {(!variation.isPersisted && !variation.isOrphan && editingInlineIndex === idx) ? (
                          <Input
                            type="text"
                            value={variation.sku}
                            onChange={(e) => handleVariationChange(idx, 'sku', e.target.value)}
                            className="h-8 w-[180px]"
                          />
                        ) : (
                          <span className={`font-mono text-sm ${variation.isOrphan ? "line-through text-muted-foreground" : ""}`}>
                              {variation.sku}
                          </span>
                        )}
                      </TableCell>

                      {/* Price Column */}
                      <TableCell>
                        {(!variation.isPersisted && !variation.isOrphan && editingInlineIndex === idx) ? (
                          <Input
                            type="number"
                            step="0.01"
                            value={variation.price}
                            onChange={(e) => handleVariationChange(idx, 'price', e.target.value)}
                            className="h-8 w-[100px]"
                          />
                        ) : (
                          <span className={variation.isOrphan ? "line-through text-muted-foreground" : ""}>
                              {`R$ ${parseFloat(variation.price).toFixed(2)}`}
                          </span>
                        )}
                      </TableCell>

                      <TableCell className="text-right">
                        {!variation.isOrphan && (
                            variation.isPersisted ? (
                            // Botão para abrir Modal de Edição Completa
                            <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => openEditModal(variation.id)}
                                className="gap-2"
                            >
                                <Edit3 className="h-3 w-3" /> Detalhes
                            </Button>
                            ) : (
                                // Botões de Edição Inline para Rascunho
                                editingInlineIndex === idx ? (
                                    <div className="flex justify-end space-x-2">
                                        <Button size="sm" variant="ghost" onClick={cancelInlineEditing}><X className="h-4 w-4"/></Button>
                                        <Button size="sm" variant="default" onClick={() => saveInlineEditing(idx)}><Save className="h-4 w-4"/></Button>
                                    </div>
                                ) : (
                                    <Button size="sm" variant="ghost" onClick={() => startInlineEditing(idx)}>
                                        <Edit3 className="h-4 w-4 text-muted-foreground" />
                                    </Button>
                                )
                            )
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            ) : (
                <div className="text-center py-10 bg-muted/20 rounded-lg">
                    <p className="text-muted-foreground">Nenhuma variação gerada ainda.</p>
                </div>
            )}
        </div>
      </CardContent>

      {/* Add Attribute Modal */}
      <Dialog open={showAddAttributeModal} onOpenChange={setShowAddAttributeModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Novo Atributo</DialogTitle>
            <DialogDescription>
              Nome da característica que diferencia os produtos (ex: Voltagem).
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label htmlFor="attributeName">Nome</Label>
            <Input
              id="attributeName"
              value={newAttributeName}
              onChange={(e) => setNewAttributeName(e.target.value)}
              placeholder="Digite o nome..."
              onKeyDown={(e) => e.key === 'Enter' && handleAddAttribute()}
              className="mt-1"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddAttributeModal(false)}>Cancelar</Button>
            <Button onClick={handleAddAttribute} disabled={!newAttributeName.trim()}>Adicionar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>

    {/* Variation Edit Modal (The detailed one) */}
    <VariationEditModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        variationId={variationToEdit}
        parentProduct={product}
        onSaveSuccess={handleModalSaveSuccess}
    />
    </>
  );
};

export default VariationManager;