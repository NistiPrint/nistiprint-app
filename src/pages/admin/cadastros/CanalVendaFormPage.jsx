import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import BlingAccountService from '@/services/BlingAccountService';
import CanalVendaService from '@/services/CanalVendaService';
import PlataformaService from '@/services/PlataformaService';
import PontoColetaService from '@/services/PontoColetaService';
import { zodResolver } from '@hookform/resolvers/zod';
import { Edit, Loader2, Plus, PlusCircle, Trash2, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';

const canalVendaSchema = z.object({
  nome: z.string().min(1, { message: "Nome é obrigatório." }),
  slug: z.string().optional().nullable(),
  plataforma: z.string().min(1, { message: "Plataforma é obrigatória." }),
  conta_bling_id: z.string().min(1, { message: "Conta Bling é obrigatória." }),
  horario_coleta: z.string().optional().nullable(),
  configuracao: z.object({}).default({}),
  regras_logisticas: z.record(z.string(), z.array(z.object({
    tipo: z.enum(['COLETA_LOCAL', 'PONTO_COLETA']),
    horario_limite: z.string(),
    ponto_coleta_id: z.string().optional().nullable(),
    prioridade_uso: z.number().default(1)
  }))).default({}),
  flex: z.boolean().default(false),
  fulfillment: z.boolean().default(false),
  color: z.string().default('#007bff'),
  ativo: z.boolean().default(false),
});

function CanalVendaFormPage() {
  const { id: canalId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [contasBling, setContasBling] = useState([]);
  const [plataformas, setPlataformas] = useState([]);
  const [pontosColeta, setPontosColeta] = useState([]);
  const [localRegras, setLocalRegras] = useState({});

  const isEditing = !!canalId;

  const form = useForm({
    resolver: zodResolver(canalVendaSchema),
    defaultValues: {
      nome: '',
      slug: '',
      plataforma: '',
      conta_bling_id: '',
      horario_coleta: '',
      configuracao: {},
      regras_logisticas: {},
      flex: false,
      fulfillment: false,
      color: '#007bff',
      ativo: false,
    },
  });

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true);
      try {
        const [contasData, plataformasData, pontosData] = await Promise.all([
          BlingAccountService.search(''),
          PlataformaService.getAll(),
          PontoColetaService.getAll(true)
        ]);
        
        setContasBling(contasData || []);
        setPlataformas(plataformasData || []);
        setPontosColeta(pontosData || []);

        if (isEditing) {
          const response = await CanalVendaService.getById(canalId);
          const data = response.canal;
          
          const config = data.configuracao || {};
          // As regras logísticas agora vêm separadas
          const regras = data.regras_logisticas || {};

          setLocalRegras(regras);

          form.reset({
            nome: data.nome || '',
            slug: data.slug || '',
            plataforma: data.plataforma || data.platform_type || '',
            conta_bling_id: data.conta_bling_id?.toString() || '',
            horario_coleta: data.horario_coleta || '',
            configuracao: config, // Manter apenas a configuração geral
            flex: !!data.flex,
            fulfillment: !!data.fulfillment,
            color: data.color || '#007bff',
            ativo: !!data.ativo,
          });
        }
      } catch (error) {
        toast.error(`Erro ao carregar dados: ${error.message}`);
        navigate('..');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchFormData();
  }, [canalId, navigate, form, isEditing]);

  // Sincroniza localRegras com o campo de regras_logisticas do formulário
  useEffect(() => {
    form.setValue("regras_logisticas", localRegras, { shouldDirty: true });
  }, [localRegras, form]);

  const addRegra = (modalidade) => {
    setLocalRegras(prev => {
      const novasRegras = [...(prev[modalidade] || [])];
      novasRegras.push({
        tipo: 'COLETA_LOCAL',
        horario_limite: '15:00',
        ponto_coleta_id: null,
        prioridade_uso: novasRegras.length + 1
      });
      return { ...prev, [modalidade]: novasRegras };
    });
  };

  const removeRegra = (modalidade, index) => {
    setLocalRegras(prev => {
      const novasRegras = [...(prev[modalidade] || [])];
      novasRegras.splice(index, 1);
      return { ...prev, [modalidade]: novasRegras };
    });
  };

  const updateRegra = (modalidade, index, field, value) => {
    setLocalRegras(prev => {
      const novasRegras = [...(prev[modalidade] || [])];
      novasRegras[index] = { ...novasRegras[index], [field]: value };
      return { ...prev, [modalidade]: novasRegras };
    });
  };


  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      // Incluir as regras logísticas no payload no nível raiz
      const payload = {
        ...data,
        configuracao: {
          ...data.configuracao
        },
        regras_logisticas: localRegras
      };

      console.log('Enviando payload:', payload);

      if (isEditing) {
        await CanalVendaService.update(canalId, payload);
        toast.success('Canal de venda atualizado com sucesso!');
      } else {
        await CanalVendaService.create(payload);
        toast.success('Canal de venda criado com sucesso!');
      }
      navigate('/cadastros/canal-venda');  // Redireciona para a lista de canais de venda
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) return <div className="text-center py-4 text-muted-foreground">Carregando Canal de Venda...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Canal de Venda' : 'Novo Canal de Venda'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="nome"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nome *</FormLabel>
                  <FormControl>
                    <Input placeholder="Nome do Canal de Venda" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="slug"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Slug</FormLabel>
                  <FormControl>
                    <Input 
                      placeholder="Slug (gerado automaticamente se vazio)" 
                      {...field} 
                      value={field.value || ''}
                      onChange={(e) => {
                        const formattedValue = e.target.value
                          .toLowerCase()
                          .replace(/\s+/g, '-')
                          .replace(/[^a-z0-9-]/g, '');
                        field.onChange(formattedValue);
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="plataforma"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Plataforma *</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value || ''}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione a plataforma" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {plataformas.map(p => (
                        <SelectItem key={p.id} value={p.nome}>{p.nome}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="conta_bling_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Conta Bling *</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value || ''}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione uma conta Bling" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {contasBling.map(conta => (
                        <SelectItem key={conta.id} value={conta.id.toString()}>{conta.text}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="horario_coleta"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Horário de Coleta</FormLabel>
                  <FormControl>
                    <Input type="time" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="color"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Cor do Canal</FormLabel>
                  <FormControl>
                    <div className="flex gap-2">
                      <Input type="color" {...field} value={field.value || '#007bff'} className="h-10 w-20 p-1" />
                      <Input type="text" {...field} value={field.value || '#007bff'} className="flex-1" />
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <FormField
                control={form.control}
                name="flex"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center space-x-3 space-y-0 rounded-md border p-3 shadow-sm">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="cursor-pointer">Flex</FormLabel>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="fulfillment"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center space-x-3 space-y-0 rounded-md border p-3 shadow-sm">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="cursor-pointer">Full</FormLabel>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="ativo"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center space-x-3 space-y-0 rounded-md border p-3 shadow-sm">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="cursor-pointer">Ativo</FormLabel>
                  </FormItem>
                )}
              />
            </div>

            <Separator className="my-4" />
            
            <div className="space-y-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Truck className="h-5 w-5" /> Regras de Envio e Coleta
              </h3>
              <p className="text-sm text-muted-foreground">
                Configure as janelas de despacho e backups por modalidade. A produção será priorizada pelo deadline final.
              </p>

              {['STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA'].map((modalidade) => (
                <div key={modalidade} className="border rounded-lg p-4 space-y-3 bg-muted/30">
                  <div className="flex items-center justify-between">
                    <h4 className="font-bold text-sm uppercase">{modalidade}</h4>
                    <Button 
                      type="button" 
                      variant="outline" 
                      size="sm" 
                      onClick={() => addRegra(modalidade)}
                    >
                      <Plus className="h-4 w-4 mr-1" /> Add Janela
                    </Button>
                  </div>

                  {(!localRegras[modalidade] || localRegras[modalidade].length === 0) ? (
                    <div className="text-xs text-muted-foreground italic text-center py-2">
                      Nenhuma regra configurada. Usará horários padrão do sistema.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {localRegras[modalidade].map((regra, idx) => (
                        <div key={idx} className="flex flex-wrap items-end gap-3 bg-white p-3 rounded border shadow-sm">
                          <div className="flex-1 min-w-[120px]">
                            <label className="text-[10px] font-bold uppercase text-muted-foreground">Tipo</label>
                            <Select 
                              value={regra.tipo} 
                              onValueChange={(val) => updateRegra(modalidade, idx, 'tipo', val)}
                            >
                              <SelectTrigger className="h-8">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="COLETA_LOCAL">Coleta Local</SelectItem>
                                <SelectItem value="PONTO_COLETA">Ponto de Coleta</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="w-24">
                            <label className="text-[10px] font-bold uppercase text-muted-foreground">Limite</label>
                            <Input 
                              type="time" 
                              className="h-8" 
                              value={regra.horario_limite}
                              onChange={(e) => updateRegra(modalidade, idx, 'horario_limite', e.target.value)}
                            />
                          </div>

                          {regra.tipo === 'PONTO_COLETA' && (
                            <div className="flex-1 min-w-[150px]">
                              <label className="text-[10px] font-bold uppercase text-muted-foreground">Local</label>
                              <Select 
                                value={regra.ponto_coleta_id?.toString() || ''} 
                                onValueChange={(val) => updateRegra(modalidade, idx, 'ponto_coleta_id', val)}
                              >
                                <SelectTrigger className="h-8">
                                  <SelectValue placeholder="Selecione o ponto" />
                                </SelectTrigger>
                                <SelectContent>
                                  {pontosColeta.map(p => (
                                    <SelectItem key={p.id} value={p.id.toString()}>{p.nome}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                          )}

                          <Button 
                            type="button" 
                            variant="ghost" 
                            size="icon" 
                            className="h-8 w-8 text-destructive"
                            onClick={() => removeRegra(modalidade, idx)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Canal
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate('/cadastros/canal-venda')} className="flex-1">
                Cancelar
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default CanalVendaFormPage;