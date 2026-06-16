import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  ExternalLink,
  FileText,
  Loader2,
  ShieldCheck,
  Webhook,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import MarketplaceService from '@/services/MarketplaceService';

const isMarketplaceModule = (moduleId) => moduleId && moduleId !== 'bling';
const supportsDirectIngest = (moduleId) => moduleId?.includes('shopee') || moduleId === 'mercadolivre';
const isDummyModule = (module) =>
  module?.auth_flow === 'dummy' ||
  module?.data_mapping_spec?.dummy === true ||
  module?.config_schema?.properties?.dummy === true;

const identityKindForModule = (moduleId) => {
  if (moduleId?.includes('shopee')) return 'shop_id';
  if (moduleId === 'mercadolivre') return 'user_id';
  if (moduleId?.includes('amazon')) return 'seller_id';
  return 'account_id';
};

const identityLabelForModule = (moduleId) => {
  const kind = identityKindForModule(moduleId);
  if (kind === 'shop_id') return 'Shop ID';
  if (kind === 'user_id') return 'User/Seller ID';
  if (kind === 'seller_id') return 'Seller ID';
  return 'Identificador da conta';
};

const getInstallationIdentity = (installation) => {
  const config = installation?.config || {};
  const credentials = installation?.credentials || {};
  return (
    config.account_identifiers?.primary ||
    config.shop_id ||
    config.seller_id ||
    config.user_id ||
    config.account_id ||
    credentials.account_identifiers?.primary ||
    credentials.shop_id ||
    credentials.seller_id ||
    credentials.user_id ||
    credentials.account_id ||
    ''
  );
};

const mergeIdentityConfig = (baseConfig, moduleId, identifier, source = 'manual') => {
  const primary = identifier?.trim();
  if (!primary) return baseConfig || {};
  const kind = identityKindForModule(moduleId);
  return {
    ...(baseConfig || {}),
    [kind]: primary,
    account_identifiers: {
      primary,
      kind,
      aliases: [],
      source,
    },
  };
};

const InstallWizard = () => {
  const { moduleId } = useParams();
  const navigate = useNavigate();

  const [module, setModule] = useState(null);
  const [currentStep, setCurrentStep] = useState(1);
  const [formData, setFormData] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [instanceId, setInstanceId] = useState(null);
  const [authUrl, setAuthUrl] = useState(null);
  const [blingStores, setBlingStores] = useState([]);
  const [selectedBlingStoreId, setSelectedBlingStoreId] = useState('');
  const [ingestOriginMode, setIngestOriginMode] = useState(
    supportsDirectIngest(moduleId) ? 'marketplace_direct' : 'erp_bling'
  );

  useEffect(() => {
    fetchModuleDetails();
  }, [moduleId]);

  async function fetchModuleDetails() {
    try {
      const data = await MarketplaceService.getModuleDetails(moduleId);
      setModule(data);
    } catch (error) {
      console.error('Error fetching module details:', error);
      toast.error('Erro ao carregar detalhes do modulo');
    } finally {
      setIsLoading(false);
    }
  }

  function handleInputChange(field, value) {
    setFormData((prev) => ({
      ...prev,
      [field]: value,
    }));
  }

  function validateStep1() {
    if (!formData.instanceName?.trim()) {
      toast.error('Por favor, forneca um nome para esta instancia da integracao.');
      return false;
    }

    if (!isDummyModule(module) && module?.config_schema?.required) {
      for (const field of module.config_schema.required) {
        if (!formData[field]?.trim()) {
          const fieldTitle = module.config_schema.properties[field]?.title || field;
          toast.error(`Por favor, preencha o campo "${fieldTitle}".`);
          return false;
        }
      }
    }

    return true;
  }

  async function createPendingInstallation() {
    try {
      setIsProcessing(true);

      const installData = {
        module_id: moduleId,
        instance_name: formData.instanceName,
        instance_color: formData.instanceColor || '#64748b',
        description: formData.description || '',
        user_id: 'default_user',
        config: {},
      };

      if (module?.config_schema?.properties) {
        Object.keys(module.config_schema.properties).forEach((field) => {
          installData.config[field] = formData[field];
        });
      }

      installData.config = mergeIdentityConfig(
        installData.config,
        moduleId,
        formData.accountIdentifier,
        'manual'
      );

      if (isDummyModule(module)) {
        installData.config = {
          ...installData.config,
          dummy: true,
          is_placeholder: true,
          capabilities: {
            order_import: 'erp_bling',
            order_update: 'erp_bling',
            invoicing: 'erp_bling',
          },
        };
        installData.functional_scopes = ['ORDER_IMPORT', 'ORDER_UPDATE', 'INVOICING'];
      }

      const response = await MarketplaceService.installModule(installData);
      setInstanceId(response.instance_id);

      if (isDummyModule(module)) {
        toast.success('Canal de venda instalado. Configure o vinculo com o Bling na tela de integracoes.');
        setCurrentStep(3);
        return;
      }

      await fetchBlingStores();
      toast.success('Configuracao salva. Prossiga para a autorizacao OAuth.');
      setCurrentStep(2);
    } catch (error) {
      console.error('Error creating pending installation:', error);
      toast.error(`Erro ao salvar configuracao: ${error.message || 'Erro desconhecido'}`);
    } finally {
      setIsProcessing(false);
    }
  }

  async function fetchBlingStores() {
    try {
      const stores = await MarketplaceService.getBlingStores();
      setBlingStores(stores);
    } catch (error) {
      console.error('Error fetching Bling stores:', error);
      toast.error('Erro ao carregar lojas do Bling');
    }
  }

  async function saveBlingLink() {
    if (!selectedBlingStoreId) {
      toast.error('Selecione uma loja do Bling');
      return;
    }

    try {
      setIsProcessing(true);

      if (formData.accountIdentifier?.trim()) {
        const installation = await MarketplaceService.getInstallation(instanceId);
        await MarketplaceService.updateInstallation(instanceId, {
          config: mergeIdentityConfig(
            installation?.config || {},
            moduleId,
            formData.accountIdentifier,
            'manual'
          ),
        });
      }

      await MarketplaceService.createChannelLink({
        integration_id: instanceId,
        bling_loja_id: selectedBlingStoreId,
        marketplace_integration_id: instanceId,
        ingest_origin_mode: ingestOriginMode,
        process_webhooks: ingestOriginMode === 'marketplace_direct' ? false : true,
        config_json: {
          ingest_origin_mode: ingestOriginMode,
          invoicing_mode: 'erp_bling',
        },
      });

      toast.success('Loja vinculada com sucesso.');
      setCurrentStep(3);
    } catch (error) {
      toast.error(`Erro ao vincular loja: ${error.message || 'Erro desconhecido'}`);
    } finally {
      setIsProcessing(false);
    }
  }

  async function startOAuth() {
    try {
      setIsProcessing(true);

      const installDataConfig = {};
      if (module?.config_schema?.properties) {
        Object.keys(module.config_schema.properties).forEach((field) => {
          installDataConfig[field] = formData[field];
        });
      }

      const response = await MarketplaceService.initAuth(moduleId, installDataConfig, instanceId);
      if (response.auth_url) {
        setAuthUrl(response.auth_url);
        window.open(response.auth_url, '_blank', 'width=800,height=700');
        toast.info('Janela de autorizacao aberta. Finalize o login no provedor e depois continue.');
      }
    } catch (error) {
      console.error('Error initializing auth:', error);
      toast.error(`Erro ao iniciar autorizacao: ${error.response?.data?.error || error.message}`);
    } finally {
      setIsProcessing(false);
    }
  }

  async function finishInstallation() {
    if (isMarketplaceModule(moduleId) && !isDummyModule(module) && instanceId) {
      try {
        setIsProcessing(true);
        let installation = await MarketplaceService.getInstallation(instanceId);

        if (!getInstallationIdentity(installation) && formData.accountIdentifier?.trim()) {
          await MarketplaceService.updateInstallation(instanceId, {
            config: mergeIdentityConfig(
              installation?.config || {},
              moduleId,
              formData.accountIdentifier,
              'manual'
            ),
          });
          installation = await MarketplaceService.getInstallation(instanceId);
        }

        if (!getInstallationIdentity(installation)) {
          toast.error('Informe o identificador da conta no marketplace para habilitar webhooks desta instancia.');
          setCurrentStep(2.5);
          return;
        }
      } catch (error) {
        toast.error(`Erro ao validar identificador da conta: ${error.message || 'Erro desconhecido'}`);
        return;
      } finally {
        setIsProcessing(false);
      }
    }

    toast.success('Instalacao finalizada. Verifique o status na lista.');
    navigate('/configuracoes/integracoes');
  }

  async function nextStep() {
    if (currentStep === 1) {
      if (!validateStep1()) return;
      await createPendingInstallation();
      return;
    }

    if (currentStep === 2) {
      setCurrentStep(2.5);
      return;
    }

    if (currentStep === 2.5) {
      await saveBlingLink();
      return;
    }

    setCurrentStep((prev) => prev + 1);
  }

  function prevStep() {
    if (currentStep <= 1) return;
    if (currentStep === 3) {
      setCurrentStep(2.5);
      return;
    }
    if (currentStep === 2.5) {
      setCurrentStep(2);
      return;
    }
    setCurrentStep((prev) => prev - 1);
  }

  if (isLoading) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!module) {
    return (
      <Card className="mx-auto mt-12 w-full max-w-lg">
        <CardContent className="pt-6 text-center">
          <AlertCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <h2 className="mb-2 text-xl font-bold">Modulo nao encontrado</h2>
          <Button onClick={() => navigate('/configuracoes/integracoes')}>Voltar</Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="container mx-auto max-w-3xl py-8">
      <div className="mb-8 text-center">
        <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center overflow-hidden rounded-xl bg-muted">
          {module.icon_url ? (
            <img
              src={module.icon_url}
              alt={module.name}
              className="h-full w-full object-contain"
              onError={(event) => {
                event.target.style.display = 'none';
              }}
            />
          ) : (
            <ShieldCheck className="h-10 w-10 text-muted-foreground" />
          )}
        </div>
        <h1 className="mb-2 text-3xl font-bold">{module.name}</h1>
        <p className="mx-auto max-w-xl text-muted-foreground">{module.description}</p>
      </div>

      <div className="mb-8">
        <div className="relative flex items-center justify-between">
          <div className="absolute left-0 top-1/2 -z-10 h-0.5 w-full bg-muted" />
          {[1, 2, 2.5, 3].map((step, idx) => (
            <div
              key={step}
              className={`flex flex-col items-center gap-2 bg-background px-4 ${
                currentStep >= step ? 'text-primary' : 'text-muted-foreground'
              }`}
            >
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-bold transition-colors ${
                  currentStep >= step
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-muted bg-background'
                }`}
              >
                {currentStep > step ? <Check className="h-4 w-4" /> : idx + 1}
              </div>
              <span className="hidden text-sm font-medium sm:block">
                {step === 1 ? 'Config.' : step === 2 ? 'OAuth' : step === 2.5 ? 'Vincular' : 'Fim'}
              </span>
            </div>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {currentStep === 1
              ? 'Configuracao inicial'
              : currentStep === 2
                ? 'Autorizacao OAuth'
                : currentStep === 2.5
                  ? 'Vincular loja Bling'
                  : 'Verificar e concluir'}
          </CardTitle>
        </CardHeader>

        <CardContent className="space-y-6">
          {currentStep === 1 ? (
            <>
              <div className="space-y-2">
                <Label>Nome da instancia *</Label>
                <Input
                  placeholder="Ex: Minha Loja Principal"
                  value={formData.instanceName || ''}
                  onChange={(event) => handleInputChange('instanceName', event.target.value)}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Cor da instancia</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      type="color"
                      className="h-10 w-12 cursor-pointer p-1"
                      value={formData.instanceColor || '#64748b'}
                      onChange={(event) => handleInputChange('instanceColor', event.target.value)}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Descricao</Label>
                  <Input
                    placeholder="Ex: Conta usada para Outlet"
                    value={formData.description || ''}
                    onChange={(event) => handleInputChange('description', event.target.value)}
                  />
                </div>
              </div>

              {!isDummyModule(module) && module.config_schema?.properties
                ? Object.entries(module.config_schema.properties).map(([fieldName, fieldProps]) => (
                    <div key={fieldName} className="space-y-2">
                      <Label>
                        {fieldProps.title}
                        {module.config_schema.required?.includes(fieldName) ? ' *' : ''}
                      </Label>
                      <Input
                        type={fieldProps.type === 'password' ? 'password' : 'text'}
                        placeholder={fieldProps.description}
                        value={formData[fieldName] || ''}
                        onChange={(event) => handleInputChange(fieldName, event.target.value)}
                      />
                    </div>
                  ))
                : null}

              {isMarketplaceModule(moduleId) && !isDummyModule(module) ? (
                <div className="space-y-2">
                  <Label>Identificador da conta no marketplace</Label>
                  <Input
                    placeholder={`${identityLabelForModule(moduleId)} usado para identificar webhooks`}
                    value={formData.accountIdentifier || ''}
                    onChange={(event) => handleInputChange('accountIdentifier', event.target.value)}
                  />
                  <p className="text-sm text-muted-foreground">
                    Preencha apenas se o provedor nao retornar esse identificador automaticamente no callback.
                  </p>
                </div>
              ) : null}
            </>
          ) : null}

          {currentStep === 2 ? (
            <div className="rounded-lg border-2 border-dashed bg-muted/30 p-8">
              {isDummyModule(module) ? (
                <div className="text-center text-sm text-muted-foreground">
                  Este modulo cria apenas uma origem de venda. Nao ha autenticacao direta.
                </div>
              ) : (
                <div className="space-y-4 text-center">
                  <Button onClick={startOAuth} disabled={isProcessing} size="lg" className="gap-2">
                    {isProcessing ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ExternalLink className="h-4 w-4" />
                    )}
                    Autorizar com {module.name}
                  </Button>
                  <div className="space-y-1 text-sm text-muted-foreground">
                    <p>O backend inicia a sessao OAuth com callback fixo e validacao de state.</p>
                    <p>Depois de autorizar no provedor, volte aqui e avance para vincular a loja.</p>
                    {authUrl ? <p className="break-all">Ultima URL iniciada: {authUrl}</p> : null}
                  </div>
                </div>
              )}
            </div>
          ) : null}

          {currentStep === 2.5 ? (
            <div className="space-y-4">
              {isMarketplaceModule(moduleId) && !isDummyModule(module) ? (
                <div className="space-y-2">
                  <Label>Identificador da conta no marketplace</Label>
                  <Input
                    placeholder={`${identityLabelForModule(moduleId)} usado para identificar webhooks`}
                    value={formData.accountIdentifier || ''}
                    onChange={(event) => handleInputChange('accountIdentifier', event.target.value)}
                  />
                </div>
              ) : null}

              <p className="text-muted-foreground">
                Vincule esta integracao a uma loja do Bling para processamento de pedidos.
              </p>

              <Select value={selectedBlingStoreId} onValueChange={setSelectedBlingStoreId}>
                <SelectTrigger>
                  <SelectValue placeholder="Selecione uma loja do Bling" />
                </SelectTrigger>
                <SelectContent>
                  {blingStores.map((store) => (
                    <SelectItem key={store.id} value={store.id.toString()}>
                      {store.nome}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="space-y-3 rounded-lg border p-3">
                <div className="flex items-start gap-2">
                  <Webhook className="mt-0.5 h-4 w-4 text-muted-foreground" />
                  <div>
                    <Label className="text-sm font-medium">Importacao de pedidos</Label>
                    <p className="text-xs text-muted-foreground">
                      Escolha se os pedidos entram direto pelo marketplace ou pelo webhook do Bling.
                    </p>
                  </div>
                </div>
                <Select value={ingestOriginMode} onValueChange={setIngestOriginMode}>
                  <SelectTrigger>
                    <SelectValue placeholder="Origem dos pedidos" />
                  </SelectTrigger>
                  <SelectContent>
                    {supportsDirectIngest(moduleId) ? (
                      <SelectItem value="marketplace_direct">Webhook direto do marketplace</SelectItem>
                    ) : null}
                    <SelectItem value="erp_bling">Webhook do Bling vinculado</SelectItem>
                    <SelectItem value="erp_only_dummy">Somente Bling (sem conta direta)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-start gap-2 rounded-lg border p-3">
                <FileText className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <div>
                  <Label className="text-sm font-medium">Emissao de nota fiscal</Label>
                  <p className="text-xs text-muted-foreground">
                    A loja Bling selecionada sera usada para emitir NF desta conta de marketplace.
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {currentStep === 3 ? (
            <div className="p-6 text-center">
              <Check className="mx-auto mb-4 h-16 w-16 text-green-500" />
              <h3 className="text-xl font-bold">Instalacao concluida!</h3>
            </div>
          ) : null}
        </CardContent>

        <CardFooter className="flex justify-between">
          <Button
            variant="outline"
            onClick={prevStep}
            disabled={currentStep === 1 || isProcessing || currentStep === 3}
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Voltar
          </Button>

          {currentStep < 3 ? (
            <Button onClick={nextStep} disabled={isProcessing}>
              {currentStep === 2 ? 'Ja autorizei, continuar' : currentStep === 2.5 ? 'Vincular' : 'Proximo'}
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={finishInstallation}>
              <Check className="mr-2 h-4 w-4" />
              Concluir
            </Button>
          )}
        </CardFooter>
      </Card>
    </div>
  );
};

export default InstallWizard;
