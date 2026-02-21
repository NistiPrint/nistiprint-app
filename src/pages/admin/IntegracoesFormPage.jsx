import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { zodResolver } from '@hookform/resolvers/zod';
import { Edit, Loader2, PlusCircle, Share2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';

const integrationSchema = z.object({
  account_name: z.string().min(1, { message: "Nome da conta é obrigatório." }),
  cnpj: z.string().min(1, { message: "CNPJ é obrigatório." }),
  client_id: z.string().optional(),
  client_secret: z.string().optional(),
  access_token: z.string().optional(),
  refresh_token: z.string().optional(),
  expires_in: z.preprocess(
    (val) => (val ? Number(val) : undefined),
    z.number().int().positive({ message: "Expires In deve ser um número inteiro positivo." }).optional()
  ),
  platform_name: z.string().optional(),
  icon_url: z.string().optional(),
});

function IntegracoesFormPage() {
  const { id: accountId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [loadingStores, setLoadingStores] = useState(false);
  const [stores, setStores] = useState([]);
  const [storeMappings, setStoreMappings] = useState({});

  const form = useForm({
    resolver: zodResolver(integrationSchema),
    defaultValues: {
      account_name: '',
      cnpj: '',
      client_id: '',
      client_secret: '',
      access_token: '',
      refresh_token: '',
      expires_in: undefined,
      platform_name: '',
      icon_url: '',
    },
  });

  const fetchStores = async () => {
    if (!accountId) return;
    setLoadingStores(true);
    try {
      const response = await fetch(`/api/v2/integracoes/stores/${accountId}`);
      if (!response.ok) {
        throw new Error('Falha ao buscar lojas.');
      }
      const data = await response.json();
      setStores(data.stores || []);
      if (data.mappings) {
          setStoreMappings(prev => ({...prev, ...data.mappings}));
      }
      toast.success('Lojas sincronizadas com sucesso!');
    } catch (error) {
      console.error(error);
      toast.error('Erro ao buscar lojas do Bling. Verifique o token.');
    } finally {
      setLoadingStores(false);
    }
  };

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true);
      try {
        if (accountId) {
          const accountResponse = await fetch(`/api/v2/integracoes/${accountId}`, {
            headers: { 'Accept': 'application/json' }
          });
          if (!accountResponse.ok) throw new Error('Integração não encontrada.');
          const accountData = await accountResponse.json();
          form.reset({
            account_name: accountData.account.account_name || '',
            cnpj: accountData.account.cnpj || '',
            client_id: accountData.account.client_id || '',
            client_secret: accountData.account.client_secret || '',
            access_token: accountData.account.access_token || '',
            refresh_token: accountData.account.refresh_token || '',
            expires_in: accountData.account.expires_in || undefined,
            platform_name: accountData.account.platform_name || '',
            icon_url: accountData.account.icon_url || '',
          });
          
          // Set initial mappings if available
          if (accountData.account.store_mappings) {
            setStoreMappings(accountData.account.store_mappings);
          }
          
          // Attempt to load stores if token exists
          if (accountData.account.access_token) {
              fetchStores(); 
          }
        }
      } catch (error) {
        toast.error(`Erro ao carregar dados da integração: ${error.message}`);
        if (accountId) navigate('/integracoes'); // Redirect on error for edit
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchFormData();
  }, [accountId, navigate, form]);

  const handleMappingChange = (storeId, platform) => {
    setStoreMappings(prev => ({
      ...prev,
      [storeId]: platform
    }));
  };

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      const method = accountId ? 'PUT' : 'POST';
      // Add trailing slash for POST to avoid 308 redirect which can cause CORS issues
      const url = accountId ? `/api/v2/integracoes/${accountId}` : '/api/v2/integracoes/';
      
      const payload = {
          ...data,
          store_mappings: storeMappings
      };

      const response = await fetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Erro ao salvar integração.');
      }

      const result = await response.json();
      toast.success(result.message || 'Integração salva com sucesso!');
      navigate('/integracoes');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4">Carregando formulário de integração...</div>;

  return (
    <Card className="max-w-4xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {accountId ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {accountId ? 'Editar Integração' : 'Nova Integração'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">
            <div className="space-y-6">
                <h3 className="text-lg font-medium">Dados da Conta</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField
                    control={form.control}
                    name="account_name"
                    render={({ field }) => (
                        <FormItem>
                        <FormLabel>Nome da Conta</FormLabel>
                        <FormControl>
                            <Input placeholder="Nome da conta (ex: Bling Nisti Print)" {...field} />
                        </FormControl>
                        <FormMessage />
                        </FormItem>
                    )}
                    />
                    <FormField
                    control={form.control}
                    name="cnpj"
                    render={({ field }) => (
                        <FormItem>
                        <FormLabel>CNPJ</FormLabel>
                        <FormControl>
                            <Input placeholder="CNPJ da conta Bling" {...field} />
                        </FormControl>
                        <FormMessage />
                        </FormItem>
                    )}
                    />
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <FormField
                    control={form.control}
                    name="platform_name"
                    render={({ field }) => (
                    <FormItem>
                        <FormLabel>Plataforma (opcional)</FormLabel>
                        <FormControl>
                        <Input placeholder="Ex: Shopee, Amazon" {...field} />
                        </FormControl>
                        <FormDescription>Identificador da plataforma para esta conta.</FormDescription>
                        <FormMessage />
                    </FormItem>
                    )}
                />
                <FormField
                    control={form.control}
                    name="icon_url"
                    render={({ field }) => (
                    <FormItem>
                        <FormLabel>URL do Ícone (opcional)</FormLabel>
                        <FormControl>
                        <Input placeholder="https://..." {...field} />
                        </FormControl>
                        <FormDescription>Ícone para exibição nas listagens.</FormDescription>
                        <FormMessage />
                    </FormItem>
                    )}
                />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField
                    control={form.control}
                    name="client_id"
                    render={({ field }) => (
                        <FormItem>
                        <FormLabel>Client ID</FormLabel>
                        <FormControl>
                            <Input placeholder="Client ID da aplicação Bling" {...field} />
                        </FormControl>
                        <FormMessage />
                        </FormItem>
                    )}
                    />
                    <FormField
                    control={form.control}
                    name="client_secret"
                    render={({ field }) => (
                        <FormItem>
                        <FormLabel>Client Secret</FormLabel>
                        <FormControl>
                            <Input placeholder="Client Secret da aplicação Bling" {...field} />
                        </FormControl>
                        <FormMessage />
                        </FormItem>
                    )}
                    />
                </div>
                
                <FormField
                control={form.control}
                name="access_token"
                render={({ field }) => (
                    <FormItem>
                    <FormLabel>Access Token</FormLabel>
                    <FormControl>
                        <Input placeholder="Access Token (gerado automaticamente)" {...field} />
                    </FormControl>
                    <FormMessage />
                    </FormItem>
                )}
                />
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField
                    control={form.control}
                    name="refresh_token"
                    render={({ field }) => (
                        <FormItem>
                        <FormLabel>Refresh Token</FormLabel>
                        <FormControl>
                            <Input placeholder="Refresh Token (gerado automaticamente)" {...field} />
                        </FormControl>
                        <FormMessage />
                        </FormItem>
                    )}
                    />
                    <FormField
                    control={form.control}
                    name="expires_in"
                    render={({ field }) => (
                        <FormItem>
                        <FormLabel>Expires In (segundos)</FormLabel>
                        <FormControl>
                            <Input type="number" placeholder="Tempo de expiração do Access Token" {...field} onChange={e => field.onChange(e.target.value ? parseInt(e.target.value) : undefined)} />
                        </FormControl>
                        <FormMessage />
                        </FormItem>
                    )}
                    />
                </div>
            </div>

            {accountId && (
                <div className="space-y-4 pt-6 border-t">
                    <div className="flex items-center justify-between">
                        <h3 className="text-lg font-medium">Mapeamento de Lojas Virtuais</h3>
                        <Button type="button" variant="outline" onClick={fetchStores} disabled={loadingStores}>
                            {loadingStores ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                            Sincronizar Lojas do Bling
                        </Button>
                    </div>
                    
                    {stores.length > 0 ? (
                        <div className="border rounded-md">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>ID Loja</TableHead>
                                        <TableHead>Nome no Bling</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead>Plataforma Vinculada</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {stores.map((store) => (
                                        <TableRow key={store.id}>
                                            <TableCell className="font-medium">{store.id}</TableCell>
                                            <TableCell>{store.descricao}</TableCell>
                                            <TableCell>{store.situacao ? 'Ativo' : 'Inativo'}</TableCell>
                                            <TableCell>
                                                <select
                                                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                                                    value={storeMappings[store.id] || ''}
                                                    onChange={(e) => handleMappingChange(store.id, e.target.value)}
                                                >
                                                    <option value="">Selecione uma plataforma...</option>
                                                    <option value="Shopee">Shopee</option>
                                                    <option value="Amazon">Amazon</option>
                                                    <option value="MercadoLivre">Mercado Livre</option>
                                                    <option value="Shein">Shein</option>
                                                    <option value="Magalu">Magalu</option>
                                                    <option value="B2W">B2W</option>
                                                    <option value="ViaVarejo">Via Varejo</option>
                                                    <option value="Outro">Outro</option>
                                                </select>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    ) : (
                        <div className="text-center py-8 text-muted-foreground border rounded-md border-dashed">
                            Clique em "Sincronizar Lojas" para carregar as lojas disponíveis nesta conta Bling.
                        </div>
                    )}
                </div>
            )}

            <div className="pt-4">
                <Button type="submit" disabled={loadingSubmit} className="w-full md:w-auto">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Integração
                </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default IntegracoesFormPage;