import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useLayout } from '@/contexts/LayoutContext';
import { productSchema } from '@/schemas/productSchema';
import { zodResolver } from '@hookform/resolvers/zod';
import { FileText, Loader2, Lock, Package, Palette, Settings, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

import CategoryService from '@/services/CategoryService';
import ProductService from '@/services/ProductService';
import SectorService from '@/services/SectorService';
import TagService from '@/services/TagService';
import UnitService from '@/services/UnitService';

import ArtworkManager from '@/components/produtos/ArtworkManager';
import BOMManager from '@/components/produtos/BOMManager';
import BlingLinkManager from '@/components/produtos/BlingLinkManager';
import ExternalIdentifiersManager from '@/components/produtos/ExternalIdentifiersManager';
import PrintManager from '@/components/produtos/PrintManager';
import VariationManager from '@/components/produtos/VariationManager';

function ProdutoFormPage() {
  const { id: produto_id } = useParams();
  const navigate = useNavigate();
  const { setLeftSidebarContent } = useLayout();
  const [searchParams] = useSearchParams();

  const variationIdParam = searchParams.get('variation_id');
  const cloneIdParam = searchParams.get('clone_id');

  const [loadingProduct, setLoadingProduct] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [activeTab, setActiveTab] = useState("general");
  const [productData, setProductData] = useState(null);
  const [categorias, setCategorias] = useState([]);
  const [unidades, setUnidades] = useState([]);
  const [setores, setSetores] = useState([]);
  const [availableTags, setAvailableTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [blingLinks, setBlingLinks] = useState([]);
  const [auxDataLoaded, setAuxDataLoaded] = useState(false);

  const form = useForm({
    resolver: zodResolver(productSchema),
    defaultValues: {
      sku: '',
      name: '',
      description: '',
      category_id: '',
      unit_of_measure_id: '',
      material_type: 'produto_acabado',
      cost_price: 0,
      stock_min: 0,
      stock_max: 0,
      requires_personalization: false,
      status: 'ativo',
      formato: 'simples',
      herdar_dados_pai: true,
      herdar_bom_pai: true,
      tags: [],
      external_product_links: { skus: [], names: [], ids: [] },
      artworks: [],
    },
  });

  // Setup sidebar navigation
  useEffect(() => {
    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Navegação do Produto
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            <li>
              <button
                onClick={() => handleTabChange("general")}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all w-full text-left ${
                  activeTab === "general"
                    ? "bg-muted text-primary font-medium"
                    : "hover:bg-muted"
                }`}
              >
                <Package className="h-4 w-4 shrink-0" />
                <span>Dados Gerais</span>
              </button>
            </li>
            <li>
              <button
                onClick={() => handleTabChange("bom")}
                disabled={!produto_id}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all w-full text-left ${
                  activeTab === "bom"
                    ? "bg-muted text-primary font-medium"
                    : !produto_id
                      ? "opacity-50 cursor-not-allowed"
                      : "hover:bg-muted"
                }`}
                title={!produto_id ? "Salve as informações básicas para liberar esta seção" : ""}
              >
                {produto_id ? <FileText className="h-4 w-4 shrink-0" /> : <Lock className="h-4 w-4 shrink-0" />}
                <span>
                  {form.watch('formato') === 'composicao' ? 'Composição' :
                   form.watch('formato') === 'kit' ? 'Itens do Kit' : 'Ficha Técnica'}
                </span>
                {!produto_id && <Lock className="h-3 w-3 ml-auto text-muted-foreground" />}
              </button>
            </li>
            {(!productData?.parent_id && form.watch('formato') !== 'composicao' && form.watch('formato') !== 'kit') && (
              <li>
                <button
                  onClick={() => handleTabChange("variations")}
                  disabled={!produto_id}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all w-full text-left ${
                    activeTab === "variations"
                      ? "bg-muted text-primary font-medium"
                      : !produto_id
                        ? "opacity-50 cursor-not-allowed"
                        : "hover:bg-muted"
                  }`}
                  title={!produto_id ? "Salve as informações básicas para liberar esta seção" : ""}
                >
                  {produto_id ? <Palette className="h-4 w-4 shrink-0" /> : <Lock className="h-4 w-4 shrink-0" />}
                  <span>Variações</span>
                  {!produto_id && <Lock className="h-3 w-3 ml-auto text-muted-foreground" />}
                </button>
              </li>
            )}
            <li>
              <button
                onClick={() => handleTabChange("artwork")}
                disabled={!produto_id}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all w-full text-left ${
                  activeTab === "artwork"
                    ? "bg-muted text-primary font-medium"
                    : !produto_id
                      ? "opacity-50 cursor-not-allowed"
                      : "hover:bg-muted"
                }`}
                title={!produto_id ? "Salve as informações básicas para liberar esta seção" : ""}
              >
                {produto_id ? <Palette className="h-4 w-4 shrink-0" /> : <Lock className="h-4 w-4 shrink-0" />}
                <span>Artes e Impressão</span>
                {!produto_id && <Lock className="h-3 w-3 ml-auto text-muted-foreground" />}
              </button>
            </li>
            <li>
              <button
                onClick={() => handleTabChange("integrations")}
                disabled={!produto_id}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all w-full text-left ${
                  activeTab === "integrations"
                    ? "bg-muted text-primary font-medium"
                    : !produto_id
                      ? "opacity-50 cursor-not-allowed"
                      : "hover:bg-muted"
                }`}
                title={!produto_id ? "Salve as informações básicas para liberar esta seção" : ""}
              >
                {produto_id ? <Settings className="h-4 w-4 shrink-0" /> : <Lock className="h-4 w-4 shrink-0" />}
                <span>Integrações</span>
                {!produto_id && <Lock className="h-3 w-3 ml-auto text-muted-foreground" />}
              </button>
            </li>
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);

    // Cleanup sidebar content when leaving the page
    return () => {
      setLeftSidebarContent(null);
    };
  }, [activeTab, produto_id, productData?.parent_id]);

  // Load auxiliary data
  useEffect(() => {
    const loadAuxData = async () => {
      try {
        // Carregar dados que não requerem permissões de administrador
        let cats = [];
        let units = [];
        let tags = [];

        try {
          [cats, units, tags] = await Promise.all([
            CategoryService.getAll(),
            UnitService.getAll(),
            TagService.getAll()
          ]);
        } catch (auxError) {
          console.error("Erro ao carregar dados auxiliares (categorias, unidades, tags)", auxError);
          toast.error("Erro ao carregar dados auxiliares. Algumas funcionalidades podem não funcionar corretamente.");
        }

        // Verificar se os dados retornaram corretamente
        setCategorias(cats || []);
        setUnidades(units || []);
        setAvailableTags(tags || []);

        // Carregar setores
        try {
          const sectors = await SectorService.getAll();
          setSetores(sectors || []);
        } catch (sectorError) {
          // Registrar qualquer erro ao carregar setores
          console.error("Erro ao carregar setores", sectorError);
          setSetores([]); // Definir como vazio em vez de falhar
        }

        setAuxDataLoaded(true); // Indicar que os dados auxiliares foram carregados
      } catch (error) {
        console.error("Error loading aux data", error);
        toast.error("Erro ao carregar dados auxiliares. Algumas funcionalidades podem não funcionar corretamente.");
      }
    };
    loadAuxData();
  }, []);

  // Load Product Data
  useEffect(() => {
    const loadProduct = async () => {
      const targetId = produto_id || cloneIdParam;
      
      if (!targetId) {
        setLoadingProduct(false);
        return;
      }

      try {
        const data = await ProductService.getById(targetId);
        const product = data.produto;
        
        // If editing, set productData. If cloning, we don't set it 
        // because it's effectively a new product.
        if (produto_id) {
          setProductData(product);
        }

        // Certificar-se de que o formato do produto é mantido corretamente
        const formatoProduto = product.formato || 'simples';

        form.reset({
          sku: cloneIdParam ? `${product.sku || product.sku_mestre || ''}-CLONE` : (product.sku || product.sku_mestre || ''),
          name: cloneIdParam ? `${product.name || ''} (Cópia)` : (product.name || ''),
          description: product.description || '',
          category_id: product.categoria_id ? String(product.categoria_id) : '',
          unit_of_measure_id: product.unidade_medida_id ? String(product.unidade_medida_id) : '',
          setor_responsavel_id: product.setor_responsavel_id ? String(product.setor_responsavel_id) : '',
          material_type: product.material_type || 'produto_acabado',
          cost_price: parseFloat(product.cost_price || 0),
          stock_min: product.stock_min !== null ? parseInt(product.stock_min, 10) : 0,
          stock_max: product.stock_max !== null ? parseInt(product.stock_max, 10) : 0,
          requires_personalization: !!product.requires_personalization,
          status: product.status || 'ativo',
          formato: formatoProduto,
          herdar_dados_pai: product.herdar_dados_pai !== undefined ? product.herdar_dados_pai : true,
          herdar_bom_pai: product.herdar_bom_pai !== undefined ? product.herdar_bom_pai : true,
          external_product_links: cloneIdParam ? { skus: [], names: [], ids: [] } : (product.external_product_links || { skus: [], names: [], ids: [] }),
          artworks: cloneIdParam ? [] : (product.artworks || []),
        });

        // Handle Tags
        if (product.tags && Array.isArray(product.tags)) {
          const tagIds = product.tags.map(t => String(t.tag_id));
          setSelectedTags(tagIds);
        }

        // Handle Bling Links (Store in state to pass to manager)
        if (product.bling_product_links && !cloneIdParam) {
            setBlingLinks(product.bling_product_links);
        }

      } catch (error) {
        console.error("Error loading product", error);
        toast.error("Erro ao carregar produto.");
        navigate('/produtos');
      } finally {
        setLoadingProduct(false);
      }
    };

    loadProduct();
  }, [produto_id, cloneIdParam, navigate, form]);

  const handleAddTag = (tagId) => {
    if (!tagId) return;
    const tagIdStr = String(tagId);
    if (!selectedTags.includes(tagIdStr)) {
      const newTags = [...selectedTags, tagIdStr];
      setSelectedTags(newTags);
      form.setValue('tags', newTags, { shouldDirty: true });
    }
  };

  const handleRemoveTag = (tagId) => {
    const tagIdStr = String(tagId);
    const newTags = selectedTags.filter(id => id !== tagIdStr);
    setSelectedTags(newTags);
    form.setValue('tags', newTags, { shouldDirty: true });
  };

  const onSubmit = async (data) => {
    if (loadingSubmit) return;
    setLoadingSubmit(true);
    try {
      // Exclude artworks from the main product data since they're managed separately
      const { artworks, ...productData } = data;
      const payload = {
        ...productData,
        tags: selectedTags, // Ensure tags are sent as array of IDs
        // Converter setor_responsavel_id para número se estiver presente, senão enviar null
        setor_responsavel_id: productData.setor_responsavel_id ? Number(productData.setor_responsavel_id) : null
      };

      if (produto_id) {
        await ProductService.update(produto_id, payload);
        toast.success("Produto atualizado com sucesso!");
        // Refresh product data to ensure consistency
        const updatedData = await ProductService.getById(produto_id);
        setProductData(updatedData.produto);

        // Atualizar o formato no formulário após o salvamento
        form.setValue('formato', updatedData.produto.formato || 'simples');
      } else {
        const newProduct = await ProductService.create(payload);
        toast.success("Produto criado com sucesso!");
        // Navigate with a flag to open the tab that was requested
        const targetTab = sessionStorage.getItem('targetProductTab') || 'general';
        sessionStorage.removeItem('targetProductTab');
        navigate(`/produtos/${newProduct.produto_id}/editar`, {
            state: { activeTab: targetTab },
            replace: true // Use replace to avoid back-button issues with new products
        });
      }
      return true;
    } catch (error) {
      toast.error(`Erro ao salvar: ${error.response?.data?.error || error.message}`);
      return false;
    } finally {
      setLoadingSubmit(false);
    }
  };

  const handleTabChange = async (value) => {
    if (loadingSubmit) return;

    if (value !== 'general' && !produto_id) {
      const isValid = await form.trigger();
      if (isValid) {
        sessionStorage.setItem('targetProductTab', value);
        const success = await form.handleSubmit(onSubmit)();
        if (success) {
          setActiveTab(value);
        }
      } else {
        // Show detailed validation errors
        const errors = form.formState.errors;
        const errorMessages = Object.entries(errors).map(([key, error]) =>
          `${key}: ${error.message}`
        );

        toast.error("Preencha as informações básicas antes de acessar outras abas.", {
          description: (
            <div className="space-y-1">
              <p>Erros de validação encontrados:</p>
              <ul className="list-disc list-inside text-sm">
                {errorMessages.slice(0, 3).map((msg, idx) => (
                  <li key={idx}>{msg}</li>
                ))}
                {errorMessages.length > 3 && (
                  <li>... e mais {errorMessages.length - 3} campos</li>
                )}
              </ul>
            </div>
          )
        });
      }
    } else {
      setActiveTab(value);
    }
  };

  // Restore active tab from state if available (after navigation)
  useEffect(() => {
    if (window.history.state?.usr?.activeTab) {
      setActiveTab(window.history.state.usr.activeTab);
    }
  }, []);

  // Handle navigation state restoration for new products
  useEffect(() => {
    const locationState = window.history.state?.state;
    if (locationState?.activeTab) {
      setActiveTab(locationState.activeTab);
    }
  }, []);

  // Handle variation_id parameter from URL
  useEffect(() => {
    if (variationIdParam && produto_id && productData && !loadingProduct) {
      setActiveTab("variations");
    }
  }, [variationIdParam, produto_id, productData, loadingProduct]);

  if (loadingProduct) return <div className="flex justify-center py-10"><Loader2 className="animate-spin h-8 w-8" /></div>;

  return (
    <div className="max-w-5xl mx-auto py-4">
      {/* Header - Removed sticky behavior */}
      <div className="bg-white border-b py-6 px-6 mb-8 flex items-center justify-between rounded-lg shadow-sm">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            {produto_id ? 'Editar Produto' : (cloneIdParam ? 'Clonar Produto' : 'Novo Produto')}
          </h1>
          {productData && (
            <div className="text-sm text-muted-foreground mt-2 font-medium">
              SKU: {productData.sku_mestre || productData.sku} | {productData.name}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={() => navigate('/produtos')}>Voltar</Button>
          <Button type="submit" form="product-form" disabled={loadingSubmit} className="shadow-md">
            {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {produto_id ? 'Salvar Alterações' : 'Criar Produto'}
          </Button>
        </div>
      </div>

      <Form {...form}>
        {/* Conditional rendering based on activeTab */}
        {activeTab === "general" && (
          <Card>
            <CardHeader>
              <CardTitle>Informações Básicas</CardTitle>
            </CardHeader>
            <CardContent>
              <form id="product-form" onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                {/* Grouped fields for better organization */}
                <div className="space-y-8">
                  {/* Identification Section */}
                  <div className="border rounded-lg p-4">
                    <h3 className="text-lg font-medium mb-4 text-primary">Identificação</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <FormField
                        control={form.control}
                        name="sku"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>SKU Mestre *</FormLabel>
                            <FormControl>
                              <Input placeholder="EX: CAM-001" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="name"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Nome do Produto *</FormLabel>
                            <FormControl>
                              <Input placeholder="Camiseta Personalizada..." {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    <FormField
                      control={form.control}
                      name="description"
                      render={({ field }) => (
                        <FormItem className="mt-4">
                          <FormLabel>Descrição</FormLabel>
                          <FormControl>
                            <Input placeholder="Detalhes do produto..." {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="formato"
                      render={({ field }) => (
                        <FormItem className="mt-4">
                          <FormLabel>Formato do Produto *</FormLabel>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value || ''}
                          >
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Selecione o formato do produto" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="simples">Simples</SelectItem>
                              <SelectItem value="com_variacao">Com Variação (Pai)</SelectItem>
                              <SelectItem value="variacao">Variação (Filho)</SelectItem>
                              <SelectItem value="composicao">Composição (Manufatura)</SelectItem>
                              <SelectItem value="kit">Kit (Comercial)</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  {/* Pricing Section */}
                  <div className="border rounded-lg p-4">
                    <h3 className="text-lg font-medium mb-4 text-primary">Precificação</h3>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      <FormField
                        control={form.control}
                        name="cost_price"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Custo (R$)</FormLabel>
                            <FormControl>
                              <Input type="number" step="0.01" {...field} onChange={e => field.onChange(parseFloat(e.target.value))} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="stock_min"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Estoque Mín.</FormLabel>
                            <FormControl>
                              <Input type="number" {...field} onChange={e => field.onChange(parseInt(e.target.value))} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="stock_max"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Estoque Máx.</FormLabel>
                            <FormControl>
                              <Input type="number" {...field} onChange={e => field.onChange(parseInt(e.target.value))} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>
                  </div>

                  {/* Classification Section */}
                  <div className="border rounded-lg p-4">
                    <h3 className="text-lg font-medium mb-4 text-primary">Classificação</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <FormField
                        control={form.control}
                        name="category_id"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Categoria</FormLabel>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value ? String(field.value) : ''}
                              disabled={!auxDataLoaded} // Desabilitar enquanto dados não carregam
                            >
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder={auxDataLoaded ? "Selecione..." : "Carregando categorias..."} />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {auxDataLoaded && categorias.map(cat => (
                                  <SelectItem key={cat.id} value={String(cat.id)}>{cat.name}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="unit_of_measure_id"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Unidade</FormLabel>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value ? String(field.value) : ''}
                              disabled={!auxDataLoaded} // Desabilitar enquanto dados não carregam
                            >
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder={auxDataLoaded ? "Selecione..." : "Carregando unidades..."} />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {auxDataLoaded && unidades.map(unit => (
                                  <SelectItem key={unit.id} value={String(unit.id)}>{unit.name} ({unit.symbol})</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="setor_responsavel_id"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Setor Responsável</FormLabel>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value ? String(field.value) : ''}
                              disabled={!auxDataLoaded} // Desabilitar enquanto dados não carregam
                            >
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder={auxDataLoaded ? "Selecione o setor responsável..." : "Carregando setores..."} />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {auxDataLoaded && setores.map(setor => (
                                  <SelectItem key={setor.id} value={String(setor.id)}>{setor.nome}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="material_type"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Nível do Produto</FormLabel>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value ? String(field.value) : ''}
                            >
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Selecione..." />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                <SelectItem value="produto_acabado">Produto Acabado</SelectItem>
                                <SelectItem value="intermediario">Intermediário (Insumo)</SelectItem>
                                <SelectItem value="materia_prima">Matéria Prima</SelectItem>
                                <SelectItem value="servico">Serviço</SelectItem>
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="status"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Status</FormLabel>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value ? String(field.value) : ''}
                            >
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Selecione..." />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                <SelectItem value="ativo">Ativo</SelectItem>
                                <SelectItem value="rascunho">Rascunho</SelectItem>
                                <SelectItem value="inativo">Inativo</SelectItem>
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>
                  </div>

                  {/* Additional Options */}
                  <div className="border rounded-lg p-4">
                    <h3 className="text-lg font-medium mb-4 text-primary">Opções Adicionais</h3>
                    <FormField
                      control={form.control}
                      name="requires_personalization"
                      render={({ field }) => (
                        <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                          <FormControl>
                            <Checkbox
                              checked={field.value}
                              onCheckedChange={field.onChange}
                            />
                          </FormControl>
                          <div className="space-y-1 leading-none">
                            <FormLabel>
                              Requer Personalização
                            </FormLabel>
                            <FormDescription>
                              Marque se este produto exige personalização do cliente.
                            </FormDescription>
                          </div>
                        </FormItem>
                      )}
                    />

                    {/* Inheritance Controls for Variations */}
                    {productData?.parent_id && (
                      <div className="border rounded-lg p-4 mt-4">
                        <h3 className="text-lg font-medium mb-4 text-primary">Controles de Herança</h3>

                        <FormField
                          control={form.control}
                          name="herdar_dados_pai"
                          render={({ field }) => (
                            <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4 mb-4">
                              <FormControl>
                                <Checkbox
                                  checked={field.value}
                                  onCheckedChange={(checked) => {
                                    field.onChange(checked);
                                    if (!checked) {
                                      // If unchecking inheritance, populate with parent data (snapshot)
                                      handleSnapshotFromParent();
                                    }
                                  }}
                                />
                              </FormControl>
                              <div className="space-y-1 leading-none">
                                <FormLabel>
                                  Utilizar descrição, categoria e tags do produto pai
                                </FormLabel>
                                <FormDescription>
                                  Marque para herdar dados do produto pai. Desative para usar valores personalizados.
                                </FormDescription>
                              </div>
                            </FormItem>
                          )}
                        />

                        <FormField
                          control={form.control}
                          name="herdar_bom_pai"
                          render={({ field }) => (
                            <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                              <FormControl>
                                <Checkbox
                                  checked={field.value}
                                  onCheckedChange={field.onChange}
                                />
                              </FormControl>
                              <div className="space-y-1 leading-none">
                                <FormLabel>
                                  Utilizar a mesma estrutura (BOM) do produto pai
                                </FormLabel>
                                <FormDescription>
                                  Marque para herdar a estrutura de composição do produto pai.
                                </FormDescription>
                              </div>
                            </FormItem>
                          )}
                        />
                      </div>
                    )}

                    {/* Tags Selection */}
                    <FormField
                      control={form.control}
                      name="tags"
                      render={() => (
                        <FormItem className="mt-4">
                          <div className="space-y-3">
                            <FormLabel>Tags</FormLabel>
                            <div className="flex gap-2">
                              <Select onValueChange={handleAddTag}>
                                <SelectTrigger className="w-[200px]">
                                  <SelectValue placeholder="Adicionar Tag" />
                                </SelectTrigger>
                                <SelectContent>
                                  {availableTags
                                    .filter(t => !selectedTags.includes(String(t.id)))
                                    .map(tag => (
                                    <SelectItem key={tag.id} value={String(tag.id)}>{tag.name}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="flex flex-wrap gap-2 mt-2">
                              {selectedTags.map(tagId => {
                                const tag = availableTags.find(t => String(t.id) === String(tagId));
                                return (
                                  <Badge key={tagId} variant="secondary" className="px-3 py-1">
                                    {tag?.name || 'Unknown'}
                                    <X
                                      className="ml-2 h-3 w-3 cursor-pointer hover:text-red-500"
                                      onClick={() => handleRemoveTag(tagId)}
                                    />
                                  </Badge>
                                );
                              })}
                            </div>
                          </div>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </div>

                {/* Footer with save button */}
                <div className="bg-white py-6 border-t mt-8">
                  <div className="flex justify-end">
                    <Button type="submit" disabled={loadingSubmit} className="w-full md:w-auto shadow-sm">
                      {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      {produto_id ? 'Salvar Alterações' : 'Criar Produto'}
                    </Button>
                  </div>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        {/* Hidden submit button at the bottom for accessibility */}
        <div className="sr-only">
          <Button type="submit" form="product-form" disabled={loadingSubmit}>
            {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {produto_id ? 'Salvar Alterações' : 'Criar Produto'}
          </Button>
        </div>

        {activeTab === "bom" && form.watch('formato') !== 'com_variacao' && (
          <Card>
            <CardHeader>
              <CardTitle>
                {form.watch('formato') === 'composicao' ? 'Composição (BOM)' :
                 form.watch('formato') === 'kit' ? 'Itens do Kit (BOM)' : 'Composição (BOM)'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <BOMManager productId={produto_id} formato={form.watch('formato')} />
            </CardContent>
          </Card>
        )}

        {activeTab === "variations" && form.watch('formato') !== 'composicao' && form.watch('formato') !== 'kit' && (
          <Card>
            <CardHeader>
              <CardTitle>Variações</CardTitle>
            </CardHeader>
            <CardContent>
              <VariationManager
                product={productData || form.watch()}
                autoOpenVariationId={variationIdParam || undefined}
                onSave={async (variationsData) => {
                  if (produto_id) {
                    try {
                      // Call the backend to save variations
                      const response = await ProductService.createProductWithVariations(
                        produto_id,
                        variationsData.variations_config,
                        variationsData.variations_data
                      );
                      toast.success("Variações salvas com sucesso!");
                      // Refresh the product data
                      const updatedProduct = await ProductService.getById(produto_id);
                      setProductData(updatedProduct.produto); // Update state for VariationManager
                    } catch (error) {
                      console.error("Error saving variations:", error);
                      toast.error(`Erro ao salvar variações: ${error.message}`);
                    }
                  } else {
                    toast.error("Salve o produto primeiro antes de adicionar variações.");
                  }
                }}
              />
            </CardContent>
          </Card>
        )}

        {activeTab === "artwork" && (
          <Card>
            <CardHeader>
              <CardTitle>Artes e Impressão</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                <ArtworkManager productId={produto_id} />
                <PrintManager productId={produto_id} artworks={form.watch('artworks') || []} />
              </div>
            </CardContent>
          </Card>
        )}

        {activeTab === "integrations" && (
          <Card>
            <CardHeader>
              <CardTitle>Integrações</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <FormField
                control={form.control}
                name="external_product_links"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-base">Vínculos de Marketplace</FormLabel>
                    <FormControl>
                      <ExternalIdentifiersManager
                          value={field.value}
                          onChange={field.onChange}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="border-t pt-6">
                  <h3 className="text-lg font-semibold mb-4">Vínculos Bling</h3>
                  <BlingLinkManager
                    productId={produto_id}
                    initialLinks={blingLinks}
                    onUpdate={() => {
                      // Função para atualizar os dados do produto após alterações nos vínculos Bling
                      if (produto_id) {
                        const loadProduct = async () => {
                          try {
                            const data = await ProductService.getById(produto_id);
                            const product = data.produto;
                            setProductData(product);

                            form.reset({
                              sku: product.sku || product.sku_mestre || '',
                              name: product.name || '',
                              description: product.description || '',
                              category_id: product.categoria_id ? String(product.categoria_id) : '',
                              unit_of_measure_id: product.unidade_medida_id ? String(product.unidade_medida_id) : '',
                              setor_responsavel_id: product.setor_responsavel_id ? String(product.setor_responsavel_id) : '',
                              material_type: product.material_type || 'produto_acabado',
                              cost_price: parseFloat(product.cost_price || 0),
                              stock_min: product.stock_min !== null ? parseInt(product.stock_min, 10) : 0,
                              stock_max: product.stock_max !== null ? parseInt(product.stock_max, 10) : 0,
                              requires_personalization: !!product.requires_personalization,
                              status: product.status || 'ativo',
                              formato: product.formato || 'simples',
                              herdar_dados_pai: product.herdar_dados_pai !== undefined ? product.herdar_dados_pai : true,
                              herdar_bom_pai: product.herdar_bom_pai !== undefined ? product.herdar_bom_pai : true,
                              external_product_links: product.external_product_links || { skus: [], names: [], ids: [] },
                              artworks: product.artworks || [],
                            });
                          } catch (error) {
                            console.error("Error refreshing product data", error);
                            toast.error("Erro ao atualizar dados do produto.");
                          }
                        };

                        loadProduct();
                      }
                    }}
                  />
              </div>
            </CardContent>
          </Card>
        )}
      </Form>
    </div>
  );
}

export default ProdutoFormPage;
