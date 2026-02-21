import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from '@/components/ui/textarea';
import { zodResolver } from '@hookform/resolvers/zod';
import { Briefcase, ClipboardPaste, Edit, Loader2, PlusCircle, Trash2, Check } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useFieldArray, useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from '@/components/ui/scroll-area';

const INTERACAO_STATUS_OPTIONS = [
    'Aguardando arte',
    'Aguardando prévia',
    'Aguardando aprovação',
    'Aprovado'
];

const itemSchema = z.object({
  product_id: z.string().optional().nullable(),
  quantidade: z.preprocess(
    (val) => Number(val),
    z.number().min(1, { message: "Qtd deve ser >= 1." })
  ),
  descricao: z.string().min(1, { message: "Descrição é obrigatória." }),
  sku: z.string().optional(),
  variacao: z.string().optional(),
  miolo_nome: z.string().optional(),
  id_produto_miolo: z.string().optional().nullable(),
  observacoes: z.string().optional(),
});

const formSchema = z.object({
  nome: z.string().min(1, { message: "Nome da Demanda é obrigatório." }),
  canal_venda_id: z.string().min(1, { message: "Canal de Venda é obrigatório." }),
  data_entrega: z.string().min(1, { message: "Data de Entrega é obrigatória." }),
  horario_coleta_especifico: z.string().optional(),
  data_finalizacao_prevista: z.string().optional(),
  observacoes: z.string().optional(),

  // Novos campos de refatoração
  modalidade_logistica: z.enum(['STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA'], { message: "Modalidade logística é obrigatória." }).default('STANDARD'),
  classificacao_cliente: z.enum(['B2C', 'B2B', 'INTERNO'], { message: "Classificação do cliente é obrigatória." }).default('B2C'),

  // B2B specific fields, conditional
  empresa_cliente_nome: z.string().optional(),
  empresa_wire_o_cor: z.string().optional(),
  empresa_elastico_cor: z.string().optional(),
  empresa_interacao_status: z.string().optional(),
  empresa_pedido_plataforma_numero: z.string().optional(),
  empresa_responsavel_id: z.string().optional(),
  empresa_responsavel_nome: z.string().optional(),

  itens: z.array(itemSchema).min(1, { message: "É necessário pelo menos um item." })
}).superRefine((data, ctx) => {
  if (data.classificacao_cliente === 'B2B') {
    if (!data.empresa_cliente_nome) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Nome da Empresa/Cliente é obrigatório para demandas B2B.",
        path: ['empresa_cliente_nome'],
      });
    }
    if (!data.empresa_responsavel_id) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Responsável é obrigatório para demandas B2B.",
            path: ['empresa_responsavel_id'],
        });
    }
  }
});

function NovaDemandaPage() {
  const { id } = useParams(); // Get ID from URL for editing
  const isEditing = !!id;
  const navigate = useNavigate();
  const [channels, setChannels] = useState([]);
  const [users, setUsers] = useState([]);
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  
  // State for product search cache/results
  const [searchResults, setSearchResults] = useState({});
  const [searching, setSearching] = useState(false);
  const [openPopovers, setOpenPopovers] = useState({}); // Track open state per row
  const [mioloSearchResults, setMioloSearchResults] = useState({});
  const [mioloOpenPopovers, setMioloOpenPopovers] = useState({});

  // Function to search products
  const searchProducts = async (query) => {
    if (!query || query.length < 3) return [];

    setSearching(true);
    try {
      const response = await fetch(`/api/v2/estoque/produtos-busca?q=${encodeURIComponent(query)}&only_marketable=true`);
      const data = await response.json();

      if (data.results) {
        return data.results.map(item => ({
          id: item.id,
          name: item.text,
          sku: item.text.split(' - ')[0] || '', // Simple heuristic if needed, but text has everything
          full_text: item.text
        }));
      }
      return [];
    } catch (error) {
      console.error('Error searching products:', error);
      return [];
    } finally {
        setSearching(false);
    }
  };

  const searchMioloProducts = async (query) => {
    if (!query || query.length < 3) return [];

    try {
      const response = await fetch(`/api/v2/estoque/produtos-busca?q=${encodeURIComponent(query)}&only_marketable=true`);
      const data = await response.json();

      if (data.results) {
        return data.results.map(item => ({
          id: item.id,
          name: item.text,
          sku: item.text.split(' - ')[0] || '', // Simple heuristic if needed, but text has everything
          full_text: item.text
        }));
      }
      return [];
    } catch (error) {
      console.error('Error searching miolo products:', error);
      return [];
    }
  };

  const form = useForm({
    resolver: zodResolver(formSchema),
    defaultValues: {
      nome: '',
      canal_venda_id: '',
      data_entrega: '',
      horario_coleta_especifico: '',
      data_finalizacao_prevista: '',
      observacoes: '',
      modalidade_logistica: 'STANDARD',
      classificacao_cliente: 'B2C',
      empresa_cliente_nome: '',
      empresa_wire_o_cor: '#000000',
      empresa_elastico_cor: '#000000',
      empresa_interacao_status: 'Aguardando arte',
      empresa_pedido_plataforma_numero: '',
      empresa_responsavel_id: '',
      empresa_responsavel_nome: '',
      itens: [{ product_id: null, quantidade: 1, descricao: '', sku: '', variacao: '', miolo_nome: '', id_produto_miolo: null, observacoes: '' }]
    },
  });

  const { fields: itemFields, append: appendItem, remove: removeItem } = useFieldArray({
    control: form.control,
    name: "itens",
  });

  const [userEditedHorario, setUserEditedHorario] = useState(false);
  const [userEditedFinalizacao, setUserEditedFinalizacao] = useState(false);

  const watchClassificacao = form.watch("classificacao_cliente");
  const watchCanalVenda = form.watch("canal_venda_id");
  const watchDataEntrega = form.watch("data_entrega");
  const watchHorarioColeta = form.watch("horario_coleta_especifico");

  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const [channelsRes, usersRes] = await Promise.all([
          fetch('/api/v2/cadastros/canal-venda?active_only=true'),
          fetch('/api/v2/usuarios-setores/usuario'),
        ]);

        const channelsData = await channelsRes.json();
        const usersData = await usersRes.json();

        setChannels(channelsData.canais || []);
        setUsers(usersData.usuarios || []);

        // If editing, fetch demand details
        if (isEditing) {
            const demandRes = await fetch(`/api/v2/demanda_producao/${id}`);
            const demandData = await demandRes.json();

            if (demandData.success) {
                const d = demandData.demanda;

                // Format dates for inputs
                const formattedDateEntrega = d.data_entrega ? d.data_entrega.split('T')[0] : '';

                let formattedFinalizacao = '';
                if (d.data_finalizacao_prevista) {
                    try {
                        const dt = new Date(d.data_finalizacao_prevista);
                        if (!isNaN(dt.getTime())) {
                            // Extrair componentes locais para evitar o deslocamento do toISOString
                            const year = dt.getFullYear();
                            const month = String(dt.getMonth() + 1).padStart(2, '0');
                            const day = String(dt.getDate()).padStart(2, '0');
                            const hours = String(dt.getHours()).padStart(2, '0');
                            const minutes = String(dt.getMinutes()).padStart(2, '0');
                            formattedFinalizacao = `${year}-${month}-${day}T${hours}:${minutes}`;
                        }
                    } catch (e) {
                        console.error("Erro ao formatar data de finalização:", e);
                    }
                }

                form.reset({
                    nome: d.nome || '',
                    canal_venda_id: d.canal_venda_id ? String(d.canal_venda_id) : '',
                    data_entrega: formattedDateEntrega,
                    horario_coleta_especifico: d.horario_coleta || '',
                    data_finalizacao_prevista: formattedFinalizacao,
                    observacoes: d.observacoes || '',

                    // Novos campos de refatoração
                    modalidade_logistica: d.modalidade_logistica || 'STANDARD',
                    classificacao_cliente: d.classificacao_cliente || 'B2C',

                    empresa_cliente_nome: d.empresa_cliente_nome || '',
                    empresa_wire_o_cor: d.empresa_wire_o_cor || '#000000',
                    empresa_elastico_cor: d.empresa_elastico_cor || '#000000',
                    empresa_interacao_status: d.empresa_interacao_status || 'Aguardando arte',
                    empresa_pedido_plataforma_numero: d.empresa_pedido_plataforma_numero || '',
                    empresa_responsavel_id: d.empresa_responsavel_id ? String(d.empresa_responsavel_id) : '',
                    empresa_responsavel_nome: d.empresa_responsavel_nome || '',
                    itens: d.itens ? d.itens.map(item => ({
                        product_id: item.product_id ? String(item.product_id) : null,
                        quantidade: item.quantidade_total || item.quantidade || 1,
                        descricao: item.descricao || '',
                        sku: item.sku || '',
                        variacao: item.variacao || '',
                        miolo_nome: item.miolo_name || '',
                        id_produto_miolo: item.id_produto_miolo ? String(item.id_produto_miolo) : null,
                        observacoes: item.observacoes || ''
                    })) : []
                });
            } else {
                toast.error("Erro ao carregar dados da demanda.");
                navigate('/producao/demanda');
            }
        }

      } catch (error) {
        toast.error("Erro ao carregar dados iniciais: " + error.message);
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchInitialData();
  }, [isEditing, id, form, navigate]);

  // Efeito para preencher automaticamente o horário de coleta quando o canal de venda é selecionado
  useEffect(() => {
    if (watchCanalVenda && !userEditedHorario) {
      const canal = channels.find(c => String(c.id) === watchCanalVenda);
      if (canal && canal.horario_coleta) {
        form.setValue('horario_coleta_especifico', canal.horario_coleta);
      }
    }
  }, [watchCanalVenda, channels, form, userEditedHorario]);

  // Efeito para preencher automaticamente a data de finalização prevista quando ambos os campos estão preenchidos
  useEffect(() => {
    if (watchDataEntrega && watchHorarioColeta && !userEditedFinalizacao) {
      try {
        // watchHorarioColeta pode vir do DB como HH:mm:ss, mas o input datetime-local/Date espera algo parseável
        // Vamos garantir que pegamos apenas HH:mm para a composição da string se necessário
        const timePart = watchHorarioColeta.includes(':') ? watchHorarioColeta.split(':').slice(0, 2).join(':') : watchHorarioColeta;
        
        // Combina a data de entrega com o horário de coleta
        const dataEntregaCompleta = new Date(`${watchDataEntrega}T${timePart}`);

        if (!isNaN(dataEntregaCompleta.getTime())) {
          // Subtrai 1 hora para obter a data de finalização prevista
          dataEntregaCompleta.setHours(dataEntregaCompleta.getHours() - 1);

          // Formata para o formato aceito pelo input datetime-local (YYYY-MM-DDTHH:mm)
          // Usando fuso local para evitar que mude o dia no toISOString
          const year = dataEntregaCompleta.getFullYear();
          const month = String(dataEntregaCompleta.getMonth() + 1).padStart(2, '0');
          const day = String(dataEntregaCompleta.getDate()).padStart(2, '0');
          const hours = String(dataEntregaCompleta.getHours()).padStart(2, '0');
          const minutes = String(dataEntregaCompleta.getMinutes()).padStart(2, '0');
          
          const formatted = `${year}-${month}-${day}T${hours}:${minutes}`;
          form.setValue('data_finalizacao_prevista', formatted);
        }
      } catch (err) {
        console.error("Erro ao calcular data de finalização prevista:", err);
      }
    }
  }, [watchDataEntrega, watchHorarioColeta, form, userEditedFinalizacao]);

  // Efeito para detectar quando o usuário edita o campo de horário de coleta
  useEffect(() => {
    if (watchHorarioColeta !== undefined && watchHorarioColeta !== '') {
      setUserEditedHorario(true);
    }
  }, [watchHorarioColeta]);

  // Efeito para detectar quando o usuário edita o campo de data de finalização prevista
  const watchDataFinalizacao = form.watch("data_finalizacao_prevista");

  useEffect(() => {
    if (watchDataFinalizacao !== undefined && watchDataFinalizacao !== '') {
      setUserEditedFinalizacao(true);
    }
  }, [watchDataFinalizacao]);

  const handlePasteItems = async () => {
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      toast.error("Seu navegador não suporta leitura de clipboard ou permissão negada. Tente usar HTTPS.");
      return;
    }

    try {
      const text = await navigator.clipboard.readText();
      if (!text) {
        toast.warning("Clipboard vazio.");
        return;
      }

      const lines = text.split(/\r?\n/).filter(line => line.trim() !== '');
      const newItems = [];

      for (const line of lines) {
        const columns = line.split('\t');
        // Expected columns: item, sku, variacao, miolo, quantidade
        const item_descricao = columns[0]?.trim() || '';
        const sku = columns[1]?.trim() || '';
        const variacao = columns[2]?.trim() || '';
        const miolo = columns[3]?.trim() || '';
        const quantidadeRaw = columns[4]?.trim() || '1';

        const quantidade = parseInt(quantidadeRaw, 10);

        if (item_descricao || sku) {
            newItems.push({
                product_id: null, // Will be populated later if found
                descricao: item_descricao || sku, // Use SKU as description if description is empty - matches DB field
                sku,
                variacao,
                miolo_nome: miolo, // Matches DB field name
                quantidade: isNaN(quantidade) ? 1 : quantidade,
                observacoes: ''
            });
        }
      }

      if (newItems.length > 0) {
        // If the first item is empty (default state), remove it before appending
        const currentItems = form.getValues('itens');
        if (currentItems.length === 1 && !currentItems[0].descricao && !currentItems[0].sku) {
             removeItem(0);
        }

        // Append items to form
        appendItem(newItems);

        // Try to enrich items with product details based on SKU
        for (let i = 0; i < newItems.length; i++) {
          const itemIndex = itemFields.length + i; // Calculate the actual index after appending
          const item = newItems[i];

          if (item.sku) {
            // Search for product by SKU
            try {
                const products = await searchProducts(item.sku);
                if (products && products.length > 0) {
                  // Use the first match
                  await handleProductSelect(itemIndex, products[0]);
                }
            } catch (searchErr) {
                console.warn("Auto-enrichment failed for SKU", item.sku, searchErr);
            }
          }
        }

        toast.success(`${newItems.length} itens adicionados do clipboard!`);
      } else {
        toast.warning("Nenhum item válido encontrado no clipboard. Certifique-se de que os dados estão separados por TAB.");
      }
    } catch (err) {
      console.error("Failed to read clipboard contents: ", err);
      const msg = err?.message || String(err);
      toast.error(`Erro ao ler do clipboard: ${msg}`);
    }
  };

  const handleProductSelect = async (index, product) => {
      const parts = product.full_text.split(' - ');
      const sku = parts[0] || '';
      const name = parts.slice(1).join(' - ') || product.name;

      form.setValue(`itens.${index}.product_id`, String(product.id));
      form.setValue(`itens.${index}.descricao`, name);
      form.setValue(`itens.${index}.sku`, sku);

      // Close popover
      setOpenPopovers(prev => ({...prev, [index]: false}));

      // 2. Fetch default miolo for this product from its BOM
      try {
        const response = await fetch(`/api/v2/demanda_producao/products/${product.id}/default-miolo`);
        const data = await response.json();

        if (data.success && data.miolo) {
          form.setValue(`itens.${index}.miolo_nome`, data.miolo.nome);
          form.setValue(`itens.${index}.id_produto_miolo`, String(data.miolo.id));
        } else {
          form.setValue(`itens.${index}.miolo_nome`, '');
          form.setValue(`itens.${index}.id_produto_miolo`, '');
        }
      } catch (error) {
        console.error('Error fetching default miolo:', error);
        form.setValue(`itens.${index}.miolo_nome`, '');
        form.setValue(`itens.${index}.id_produto_miolo`, '');
      }
  };

  const onSubmit = async (data, isDraft = false) => {
    setLoadingSubmit(true);
    try {
      if (data.classificacao_cliente === 'B2B' && data.empresa_responsavel_id) {
          const selectedUser = users.find(u => String(u.id) === String(data.empresa_responsavel_id));
          if (selectedUser) {
              data.empresa_responsavel_nome = selectedUser.nome;
          }
      }

      if (data.data_finalizacao_prevista) {
        data.data_finalizacao_prevista = new Date(data.data_finalizacao_prevista).toISOString();
      }

      // Corrige o fuso horário da data de entrega para evitar deslocamento de um dia
      if (data.data_entrega) {
        // Converte a data para o início do dia no fuso horário local
        const dataEntrega = new Date(data.data_entrega);
        // Garante que a data seja tratada como início do dia (00:00:00) no fuso horário local
        data.data_entrega = dataEntrega.toISOString().split('T')[0];
      }

      // Legado: mapeia classificacao para tipo_demanda
      const tipo_demanda = data.classificacao_cliente === 'B2B' ? 'B2B' : (data.classificacao_cliente === 'INTERNO' ? 'ESTOQUE_INTERNO' : 'PLATAFORMA');

      let url = data.classificacao_cliente === 'B2B'
        ? '/api/v2/demanda_producao/empresas'
        : '/api/v2/demanda_producao/';

      let method = 'POST';

      if (isEditing) {
          url = `/api/v2/demanda_producao/${id}`;
          method = 'PUT';
      }

      const processedPayload = {
        ...data,
        is_draft: isDraft,
        tipo_demanda: tipo_demanda,
        // Mapeamento para manter compatibilidade com campos antigos
        is_flex: data.modalidade_logistica === 'EXPRESS',
        fulfillment: data.modalidade_logistica === 'FULFILLMENT',
        itens: data.itens.map(item => ({
             ...item,
             product_id: item.product_id ? parseInt(item.product_id) : null,
             id_produto_miolo: item.id_produto_miolo ? parseInt(item.id_produto_miolo) : null
        }))
      };

      if (processedPayload.classificacao_cliente !== 'B2B') {
        delete processedPayload.empresa_cliente_nome;
        delete processedPayload.empresa_wire_o_cor;
        delete processedPayload.empresa_elastico_cor;
        delete processedPayload.empresa_interacao_status;
        delete processedPayload.empresa_pedido_plataforma_numero;
        delete processedPayload.empresa_responsavel_id;
        delete processedPayload.empresa_responsavel_nome;
      }

      const response = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(processedPayload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Erro ao salvar demanda.');
      }

      const result = await response.json();
      toast.success(result.message || 'Demanda salva com sucesso!');
      navigate('/producao/demanda');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4">Carregando formulário...</div>;

  return (
    <Card className="max-w-[95%] mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : (watchClassificacao === 'B2B' ? <Briefcase className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />)}
          {isEditing ? 'Editar Demanda' : 'Nova Demanda'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={(e) => { e.preventDefault(); form.handleSubmit((data) => onSubmit(data, false))(e); }} className="space-y-6">
            
            {/* Classificação e Modalidade */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <FormField
                control={form.control}
                name="classificacao_cliente"
                render={({ field }) => (
                    <FormItem>
                    <FormLabel>Classificação do Cliente</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                        <SelectTrigger>
                            <SelectValue placeholder="Selecione a classificação" />
                        </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                            <SelectItem value="B2C">B2C (Consumidor Final)</SelectItem>
                            <SelectItem value="B2B">B2B (Venda Corporativa)</SelectItem>
                            <SelectItem value="INTERNO">Interno (Estoque/Amostra)</SelectItem>
                        </SelectContent>
                    </Select>
                    <FormMessage />
                    </FormItem>
                )}
                />
                <FormField
                control={form.control}
                name="modalidade_logistica"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Modalidade Logística</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Selecione a modalidade" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="STANDARD">Padrão</SelectItem>
                        <SelectItem value="EXPRESS">Expressa (Flex)</SelectItem>
                        <SelectItem value="FULFILLMENT">Fulfillment</SelectItem>
                        <SelectItem value="RETIRADA">Retirada</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            
            <Separator className="my-2" />

            {/* General Demand Fields */}
            <h3 className="text-lg font-semibold border-b pb-2 mb-4">Dados Gerais</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <FormField
                control={form.control}
                name="nome"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Nome da Demanda</FormLabel>
                    <FormControl>
                      <Input placeholder="Ex: Pedido Bling 12345" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="canal_venda_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Canal de Venda</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Selecione o canal" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {channels.map(channel => (
                          <SelectItem key={channel.id} value={String(channel.id)}>
                            {channel.nome}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="data_entrega"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Data de Entrega</FormLabel>
                    <FormControl>
                      <Input type="date" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="horario_coleta_especifico"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Horário de Coleta (Op)</FormLabel>
                    <FormControl>
                      <Input
                        type="time"
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          // Marcar que o usuário editou manualmente o campo
                          setUserEditedHorario(true);
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="data_finalizacao_prevista"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Finalização Prevista (Op)</FormLabel>
                    <FormControl>
                      <Input
                        type="datetime-local"
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          // Marcar que o usuário editou manualmente o campo
                          setUserEditedFinalizacao(true);
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="observacoes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Observações</FormLabel>
                    <FormControl>
                      <Textarea placeholder="Observações gerais..." rows={1} className="min-h-[40px]" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* B2B Specific Fields */}
            {watchClassificacao === 'B2B' && (
              <>
                <h3 className="text-lg font-semibold border-b pb-2 mb-4 mt-6">Detalhes B2B</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <FormField
                    control={form.control}
                    name="empresa_cliente_nome"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nome da Empresa/Cliente</FormLabel>
                        <FormControl>
                          <Input placeholder="Nome da empresa" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="empresa_pedido_plataforma_numero"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nº Pedido Plataforma</FormLabel>
                        <FormControl>
                          <Input placeholder="Nº pedido externo" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="empresa_responsavel_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Responsável</FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Selecione" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {users.map(user => (
                              <SelectItem key={user.id} value={String(user.id)}>
                                {user.nome}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="empresa_wire_o_cor"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Cor Wire-o</FormLabel>
                        <FormControl>
                          <Input type="color" {...field} className="h-10 w-full" />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="empresa_elastico_cor"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Cor Elástico</FormLabel>
                        <FormControl>
                          <Input type="color" {...field} className="h-10 w-full" />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="empresa_interacao_status"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Status Interação</FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Status" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {INTERACAO_STATUS_OPTIONS.map(status => (
                              <SelectItem key={status} value={status}>{status}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </>
            )}

            {/* Demand Items */}
            <div className="flex items-center justify-between border-b pb-2 mb-4 mt-8">
                <h3 className="text-lg font-semibold">Itens da Demanda</h3>
                <div className="flex gap-2">
                     <Button type="button" variant="outline" onClick={handlePasteItems}>
                        <ClipboardPaste className="mr-2 h-4 w-4" /> Colar Itens (Tabular)
                    </Button>
                    <Button type="button" variant="outline" onClick={() => appendItem({ product_id: null, quantidade: 1, descricao: '', sku: '', variacao: '', miolo_nome: '', id_produto_miolo: null, observacoes: '' })}>
                        <PlusCircle className="mr-2 h-4 w-4" /> Adicionar Manual
                    </Button>
                </div>
            </div>
            
            <div className="rounded-md border">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[300px]">Item (Descrição / Busca)</TableHead>
                            <TableHead className="w-[120px]">SKU</TableHead>
                            <TableHead className="w-[120px]">Variação</TableHead>
                            <TableHead className="w-[120px]">Miolo</TableHead>
                            <TableHead className="w-[80px]">Qtd</TableHead>
                            <TableHead className="w-[50px]"></TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {itemFields.map((item, index) => (
                            <TableRow key={item.id}>
                                <TableCell>
                                    <FormField
                                        control={form.control}
                                        name={`itens.${index}.descricao`}
                                        render={({ field }) => (
                                            <FormItem className="flex flex-col">
                                                <Popover 
                                                  open={openPopovers[index] && searchResults[index]?.length > 0} 
                                                  onOpenChange={(open) => {
                                                    if (!open) setOpenPopovers(prev => ({...prev, [index]: false}));
                                                  }}
                                                >
                                                  <PopoverTrigger asChild>
                                                    <FormControl>
                                                      <div className="relative w-full">
                                                        <Input
                                                            {...field}
                                                            placeholder="Digite para buscar ou descrever..."
                                                            className="h-8 pr-8"
                                                            autoComplete="off"
                                                            onChange={(e) => {
                                                                field.onChange(e.target.value);
                                                                
                                                                if (e.target.value.length >= 3) {
                                                                    searchProducts(e.target.value).then(res => {
                                                                        setSearchResults(prev => ({...prev, [index]: res}));
                                                                        setOpenPopovers(prev => ({...prev, [index]: true}));
                                                                    });
                                                                } else {
                                                                    setOpenPopovers(prev => ({...prev, [index]: false}));
                                                                }
                                                            }}
                                                        />
                                                         {form.getValues(`itens.${index}.product_id`) && (
                                                            <div className="absolute right-2 top-1/2 transform -translate-y-1/2 text-xs text-green-600 font-bold px-1 bg-green-100 rounded">
                                                                <Check className="h-3 w-3" />
                                                            </div>
                                                        )}
                                                      </div>
                                                    </FormControl>
                                                  </PopoverTrigger>
                                                  <PopoverContent 
                                                    className="p-0 w-[500px]"
                                                    align="start"
                                                    onOpenAutoFocus={(e) => e.preventDefault()}
                                                  >
                                                      <ScrollArea className="h-[200px]">
                                                          <div className="p-1">
                                                              {searchResults[index]?.map((prod) => (
                                                                  <div
                                                                      key={prod.id}
                                                                      className="cursor-pointer px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground rounded-sm"
                                                                      onClick={() => handleProductSelect(index, prod)}
                                                                  >
                                                                      {prod.full_text}
                                                                  </div>
                                                              ))}
                                                          </div>
                                                      </ScrollArea>
                                                  </PopoverContent>
                                                </Popover>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                </TableCell>
                                <TableCell>
                                    <FormField
                                        control={form.control}
                                        name={`itens.${index}.sku`}
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormControl>
                                                    <Input {...field} className="h-8" />
                                                </FormControl>
                                            </FormItem>
                                        )}
                                    />
                                </TableCell>
                                <TableCell>
                                    <FormField
                                        control={form.control}
                                        name={`itens.${index}.variacao`}
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormControl>
                                                    <Input {...field} className="h-8" />
                                                </FormControl>
                                            </FormItem>
                                        )}
                                    />
                                </TableCell>
                                <TableCell>
                                    <FormField
                                        control={form.control}
                                        name={`itens.${index}.miolo_nome`}
                                        render={({ field }) => (
                                            <FormItem className="flex flex-col">
                                                <Popover
                                                  open={mioloOpenPopovers[index] && mioloSearchResults[index]?.length > 0}
                                                  onOpenChange={(open) => {
                                                    if (!open) setMioloOpenPopovers(prev => ({...prev, [index]: false}));
                                                  }}
                                                >
                                                  <PopoverTrigger asChild>
                                                    <FormControl>
                                                      <div className="relative w-full">
                                                        <Input
                                                            {...field}
                                                            placeholder="Digite para buscar miolo..."
                                                            className="h-8 pr-8"
                                                            autoComplete="off"
                                                            onChange={(e) => {
                                                                field.onChange(e.target.value);

                                                                if (e.target.value.length >= 3) {
                                                                    searchMioloProducts(e.target.value).then(res => {
                                                                        setMioloSearchResults(prev => ({...prev, [index]: res}));
                                                                        setMioloOpenPopovers(prev => ({...prev, [index]: true}));
                                                                    });
                                                                } else {
                                                                    setMioloOpenPopovers(prev => ({...prev, [index]: false}));
                                                                }
                                                            }}
                                                        />
                                                         {form.getValues(`itens.${index}.id_produto_miolo`) && (
                                                            <div className="absolute right-2 top-1/2 transform -translate-y-1/2 text-xs text-green-600 font-bold px-1 bg-green-100 rounded">
                                                                <Check className="h-3 w-3" />
                                                            </div>
                                                        )}
                                                      </div>
                                                    </FormControl>
                                                  </PopoverTrigger>
                                                  <PopoverContent
                                                    className="p-0 w-[500px]"
                                                    align="start"
                                                    onOpenAutoFocus={(e) => e.preventDefault()}
                                                  >
                                                      <ScrollArea className="h-[200px]">
                                                          <div className="p-1">
                                                              {mioloSearchResults[index]?.map((prod) => (
                                                                  <div
                                                                      key={prod.id}
                                                                      className="cursor-pointer px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground rounded-sm"
                                                                      onClick={() => {
                                                                        form.setValue(`itens.${index}.miolo_nome`, prod.name);
                                                                        form.setValue(`itens.${index}.id_produto_miolo`, String(prod.id));
                                                                        setMioloOpenPopovers(prev => ({...prev, [index]: false}));
                                                                      }}
                                                                  >
                                                                      {prod.full_text}
                                                                  </div>
                                                              ))}
                                                          </div>
                                                      </ScrollArea>
                                                  </PopoverContent>
                                                </Popover>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                    <input
                                      type="hidden"
                                      {...form.register(`itens.${index}.id_produto_miolo`)}
                                    />
                                </TableCell>
                                <TableCell>
                                    <FormField
                                        control={form.control}
                                        name={`itens.${index}.quantidade`}
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormControl>
                                                    <Input type="number" min="1" {...field} className="h-8" />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                </TableCell>
                                <TableCell>
                                    <Button type="button" variant="ghost" size="icon" onClick={() => removeItem(index)}>
                                        <Trash2 className="h-4 w-4 text-red-500" />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            <div className="flex gap-4 mt-4">
                <Button type="button" variant="secondary" disabled={loadingSubmit} className="flex-1" onClick={form.handleSubmit((data) => onSubmit(data, true))}>
                  {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditing ? 'Salvar Alterações no Rascunho' : 'Salvar como Rascunho'}
                </Button>
                <Button type="submit" disabled={loadingSubmit} className="flex-1">
                  {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditing ? 'Atualizar e Publicar (Se Rascunho)' : 'Criar Demanda'}
                </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default NovaDemandaPage;