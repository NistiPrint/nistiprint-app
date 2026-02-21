import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import MarketplaceService from '@/services/MarketplaceService';
import { AlertCircle, ArrowLeft, ArrowRight, Check, ExternalLink, Loader2, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

const InstallWizard = () => {
  const { moduleId } = useParams();
  const navigate = useNavigate();
  const [module, setModule] = useState(null);
  const [currentStep, setCurrentStep] = useState(1);
  const [formData, setFormData] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [instanceId, setInstanceId] = useState(null); // ID of the pending installation
  const [authUrl, setAuthUrl] = useState(null);
  const [manualMode, setManualMode] = useState(false);
  const [manualRedirectUrl, setManualRedirectUrl] = useState('');

  useEffect(() => {
    fetchModuleDetails();
  }, [moduleId]);

  const fetchModuleDetails = async () => {
    try {
      const data = await MarketplaceService.getModuleDetails(moduleId);
      setModule(data);
      setIsLoading(false);
    } catch (error) {
      console.error('Error fetching module details:', error);
      toast.error("Erro ao carregar detalhes do módulo");
      setIsLoading(false);
    }
  };

  const handleInputChange = (field, value) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const nextStep = async () => {
    if (currentStep === 1) {
      if (!validateStep1()) return;
      await createPendingInstallation();
    } else if (currentStep === 2) {
      // Logic for Step 2 is handled by "Conectar" button or specific flow
      if (!validateStep2()) return;
      setCurrentStep(3);
    } else {
      setCurrentStep(prev => prev + 1);
    }
  };

  const prevStep = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const validateStep1 = () => {
    if (!formData.instanceName?.trim()) {
      toast.error('Por favor, forneça um nome para esta instância da integração.');
      return false;
    }

    if (module?.config_schema?.required) {
      for (const field of module.config_schema.required) {
        if (!formData[field]?.trim()) {
          const fieldTitle = module.config_schema.properties[field]?.title || field;
          toast.error(`Por favor, preencha o campo "${fieldTitle}".`);
          return false;
        }
      }
    }

    return true;
  };

  const createPendingInstallation = async () => {
    try {
      setIsProcessing(true);
      
      const installData = {
        module_id: moduleId,
        instance_name: formData.instanceName,
        user_id: 'default_user', // This should be handled by backend session ideally
        config: {}
      };

      if (module?.config_schema?.properties) {
        Object.keys(module.config_schema.properties).forEach(field => {
          installData.config[field] = formData[field];
        });
      }

      // Initial create without credentials (pending status)
      const response = await MarketplaceService.installModule(installData);
      setInstanceId(response.instance_id);
      
      toast.success('Configuração salva. Prossiga para autenticação.');
      setCurrentStep(2);
      
    } catch (error) {
      console.error('Error creating pending installation:', error);
      toast.error(`Erro ao salvar configuração: ${error.message || 'Erro desconhecido'}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const validateStep2 = () => {
    // For OAuth, we just check if they clicked the button (we could add a check if we had a status polling)
    // For now, we assume if they click Next they believe they are done.
    return true;
  };

  const startOAuth = async () => {
    try {
      setIsProcessing(true);
      
      const installDataConfig = {};
      if (module?.config_schema?.properties) {
        Object.keys(module.config_schema.properties).forEach(field => {
          installDataConfig[field] = formData[field];
        });
      }

      // If manual mode is active, we force the PROD redirect URL
      // This allows the backend to generate a valid signature for Shopee
      // The user will then be redirected to prod, and copy the URL back here
      let redirectUrl = null;
      if (manualMode) {
        // Hardcoded prod URL or configurable
        redirectUrl = "https://app.nistiprint.com.br/api/v2/marketplace/auth/callback/shopee";
      }

      const response = await MarketplaceService.initAuth(moduleId, installDataConfig, instanceId, redirectUrl);
      
      if (response.auth_url) {
        setAuthUrl(response.auth_url);
        window.open(response.auth_url, '_blank', 'width=800,height=700');
        toast.info("Janela de autenticação aberta. Por favor, autorize o aplicativo.");
      }
      
    } catch (error) {
      console.error('Error initializing auth:', error);
      toast.error(`Erro ao iniciar autenticação: ${error.response?.data?.error || error.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const processManualExchange = async () => {
    if (!manualRedirectUrl) {
      toast.error("Por favor, cole a URL de redirecionamento.");
      return;
    }

    try {
      setIsProcessing(true);
      const url = new URL(manualRedirectUrl);
      const code = url.searchParams.get("code");
      const shopId = url.searchParams.get("shop_id");

      if (!code) {
        toast.error("URL inválida: código não encontrado.");
        setIsProcessing(false);
        return;
      }

      await MarketplaceService.exchangeCode(moduleId, code, instanceId, shopId);
      toast.success("Autenticação manual realizada com sucesso!");
      setCurrentStep(3);

    } catch (error) {
      console.error("Manual exchange error:", error);
      toast.error("Erro ao processar URL: " + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const finishInstallation = () => {
    toast.success('Instalação finalizada! Verifique o status na lista.');
    navigate('/configuracoes/integracoes');
  };

  if (isLoading) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!module) {
    return (
      <Card className="w-full max-w-lg mx-auto mt-12">
        <CardContent className="pt-6 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <h2 className="text-xl font-bold mb-2">Módulo não encontrado</h2>
          <Button onClick={() => navigate('/configuracoes/integracoes')}>Voltar</Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="container max-w-3xl mx-auto py-8">
      <div className="mb-8 text-center">
        <div className="mx-auto h-20 w-20 bg-muted rounded-xl flex items-center justify-center mb-4 overflow-hidden">
          {module.icon_url ? (
            <img src={module.icon_url} alt={module.name} className="h-full w-full object-contain" onError={(e) => { e.target.style.display='none'; }} />
          ) : (
            <ShieldCheck className="h-10 w-10 text-muted-foreground" />
          )}
        </div>
        <h1 className="text-3xl font-bold mb-2">{module.name}</h1>
        <p className="text-muted-foreground max-w-xl mx-auto">{module.description}</p>
      </div>

      <div className="mb-8">
        <div className="flex justify-between items-center relative">
          <div className="absolute left-0 top-1/2 w-full h-0.5 bg-muted -z-10" />
          {[1, 2, 3].map((step) => (
            <div key={step} className={`flex flex-col items-center gap-2 bg-background px-4 ${currentStep >= step ? 'text-primary' : 'text-muted-foreground'}`}>
              <div className={`h-8 w-8 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-colors ${currentStep >= step ? 'border-primary bg-primary text-primary-foreground' : 'border-muted bg-background'}`}>
                {currentStep > step ? <Check className="h-4 w-4" /> : step}
              </div>
              <span className="text-sm font-medium hidden sm:block">
                {step === 1 ? 'Configuração' : step === 2 ? 'Autenticação' : 'Conclusão'}
              </span>
            </div>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {currentStep === 1 ? 'Configuração Inicial' : 
             currentStep === 2 ? 'Autenticação' : 'Verificar e Concluir'}
          </CardTitle>
          <CardDescription>
            {currentStep === 1 ? 'Defina as configurações básicas da integração.' : 
             currentStep === 2 ? `Conecte sua conta ${module.name}.` : 'Finalize o processo.'}
          </CardDescription>
        </CardHeader>
        
        <CardContent className="space-y-6">
          {currentStep === 1 && (
            <>
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  Nome da Instância *
                </label>
                <Input
                  placeholder="Ex: Minha Loja Principal"
                  value={formData.instanceName || ''}
                  onChange={(e) => handleInputChange('instanceName', e.target.value)}
                />
                <p className="text-[0.8rem] text-muted-foreground">Um nome para identificar esta integração no sistema.</p>
              </div>

              {module.config_schema?.properties && Object.entries(module.config_schema.properties).map(([field_name, field_props]) => (
                <div key={field_name} className="space-y-2">
                  <label className="text-sm font-medium leading-none">
                    {field_props.title}{module.config_schema.required?.includes(field_name) ? ' *' : ''}
                  </label>
                  {field_props.type === "textarea" ? (
                    <Textarea
                      placeholder={field_props.description}
                      value={formData[field_name] || ''}
                      onChange={(e) => handleInputChange(field_name, e.target.value)}
                    />
                  ) : field_props.type === "select" ? (
                    <Select 
                      value={formData[field_name] || ''} 
                      onValueChange={(val) => handleInputChange(field_name, val)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione uma opção" />
                      </SelectTrigger>
                      <SelectContent>
                        {field_props.enum?.map(option => (
                          <SelectItem key={option} value={option}>{option}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      type={field_props.type === "password" ? "password" : "text"}
                      placeholder={field_props.description}
                      value={formData[field_name] || ''}
                      onChange={(e) => handleInputChange(field_name, e.target.value)}
                    />
                  )}
                  <p className="text-[0.8rem] text-muted-foreground">{field_props.description}</p>
                </div>
              ))}
            </>
          )}

          {currentStep === 2 && (
            <>
              {module.auth_flow === 'oauth2' ? (
                <div className="space-y-6">
                  <div className="flex items-center space-x-2 bg-muted/50 p-4 rounded-lg">
                    <Switch id="manual-mode" checked={manualMode} onCheckedChange={setManualMode} />
                    <Label htmlFor="manual-mode" className="flex flex-col">
                      <span>Modo Manual / Desenvolvimento Local</span>
                      <span className="font-normal text-xs text-muted-foreground">
                        Ative se você estiver rodando localmente (localhost) e a plataforma exigir uma URL pública.
                      </span>
                    </Label>
                  </div>

                  <div className="flex flex-col items-center justify-center p-8 border-2 border-dashed rounded-lg bg-muted/30">
                    <p className="text-center mb-6 text-muted-foreground max-w-md">
                      {manualMode 
                        ? "1. Clique abaixo para abrir a Shopee (usando a URL de produção).\n2. Autorize o app.\n3. Quando for redirecionado (mesmo que dê erro), copie a URL completa do navegador."
                        : `Clique no botão abaixo para abrir a página de login da ${module.name}. Após autorizar, você será redirecionado automaticamente.`
                      }
                    </p>
                    
                    <Button onClick={startOAuth} disabled={isProcessing} size="lg" className="gap-2">
                      {isProcessing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                      Autorizar com {module.name}
                    </Button>
                  </div>

                  {manualMode && (
                    <div className="space-y-4 pt-4 border-t">
                      <div className="space-y-2">
                        <Label>Cole a URL de redirecionamento final aqui:</Label>
                        <div className="flex gap-2">
                          <Input 
                            placeholder="https://app.nistiprint.com.br/api/v2/marketplace/auth/callback/shopee?code=..." 
                            value={manualRedirectUrl}
                            onChange={(e) => setManualRedirectUrl(e.target.value)}
                          />
                          <Button onClick={processManualExchange} disabled={isProcessing}>
                            {isProcessing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                            Confirmar
                          </Button>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          O sistema irá extrair o código de autorização desta URL e completar a instalação localmente.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                 <div className="text-center p-8">
                    <p>Este módulo usa um método de autenticação simples (API Key ou Usuário/Senha) configurado no passo anterior.</p>
                 </div>
              )}
            </>
          )}

          {currentStep === 3 && (
            <div className="space-y-4 bg-muted/30 p-4 rounded-lg text-center">
               <div className="flex flex-col items-center justify-center p-6">
                 <Check className="h-16 w-16 text-green-500 mb-4" />
                 <h3 className="text-xl font-bold mb-2">Instalação Concluída!</h3>
                 <p className="text-muted-foreground max-w-md">
                   A integração foi ativada com sucesso.
                 </p>
               </div>
            </div>
          )}
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
             <Button onClick={nextStep} disabled={isProcessing || currentStep === 2}> 
               {/* Disable Next on Step 2 because user must authorize first, either auto or manual */} 
               {currentStep === 2 ? 'Aguardando Autorização...' : (
                <>
                  Próximo
                  <ArrowRight className="ml-2 h-4 w-4" />
                </>
               )}
            </Button>
          ) : (
            <Button onClick={finishInstallation}>
              <Check className="mr-2 h-4 w-4" />
              Concluir e Ver Lista
            </Button>
          )}
        </CardFooter>
      </Card>
    </div>
  );
};

export default InstallWizard;
