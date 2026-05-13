import React, { useState, useEffect } from 'react';
import IntegracaoCard from '@/components/integracoes/IntegracaoCard';
import VinculoModal from '@/components/integracoes/VinculoModal';
import * as integracaoCanalService from '@/services/integracaoCanalService';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Search,
  AlertCircle,
  HelpCircle,
  FileWarning,
  CheckCircle2
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';

/**
 * Tab de Configuração de Vínculos de Canais
 * Gerencia vínculos entre canais de venda, lojas Bling e integrações.
 *
 * ⚠️ IMPORTANTE: A renovação de tokens deve ser feita na aba "Integrações".
 * O botão de sincronizar Firestore foi movido para lá também.
 *
 * 📊 Para corrigir vínculos órfãos, execute:
 *    python scripts/fix_orphan_vinculos.py --create-dummies
 */
export default function IntegracoesConfigPage() {
  const [loading, setLoading] = useState(true);
  const [platforms, setPlatforms] = useState([]);
  const [canais, setCanais] = useState([]);
  const [integracoes, setIntegracoes] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [vinculoEdit, setVinculoEdit] = useState(null);
  const [plataformaFilter, setPlataformaFilter] = useState(null);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [filtroStatus, setFiltroStatus] = useState('todas'); // 'todas', 'com_problemas', 'saudaveis'

  useEffect(() => {
    carregarDados();
  }, []);

  async function carregarDados() {
    setLoading(true);
    setError('');

    try {
      const [platformsData, canaisData, integracoesData] = await Promise.all([
        integracaoCanalService.listarPlataformas(),
        integracaoCanalService.listarCanais(),
        integracaoCanalService.listarIntegracoes()
      ]);

      setPlatforms(platformsData);
      setCanais(canaisData);
      setIntegracoes(integracoesData);
    } catch (err) {
      console.error('Erro ao carregar dados:', err);
      setError('Falha ao carregar configurações. Tente recarregar a página.');
    } finally {
      setLoading(false);
    }
  }

  function handleAddVinculo(plataforma) {
    setVinculoEdit(null);
    setPlataformaFilter(plataforma);
    setModalOpen(true);
  }

  function handleEditVinculo(vinculo) {
    setVinculoEdit(vinculo);
    setPlataformaFilter(null);
    setModalOpen(true);
  }

  async function handleDeleteVinculo(vinculo) {
    if (!window.confirm(`Deseja realmente remover o vínculo para a loja ${vinculo.bling_loja_id}?`)) {
      return;
    }

    try {
      await integracaoCanalService.removerVinculo(vinculo.id);
      setSuccessMsg('Vínculo removido com sucesso');
      carregarDados();
      setTimeout(() => setSuccessMsg(''), 3000);
    } catch {
      setError('Falha ao remover vínculo');
      setTimeout(() => setError(''), 3000);
    }
  }

  async function handleToggleWebhooks(vinculo) {
    const nextValue = vinculo.process_webhooks === false;

    try {
      await integracaoCanalService.atualizarVinculo(vinculo.id, {
        process_webhooks: nextValue
      });
      setSuccessMsg(
        nextValue
          ? 'Webhooks ativados para este vínculo'
          : 'Webhooks ignorados para este vínculo'
      );
      carregarDados();
      setTimeout(() => setSuccessMsg(''), 3000);
    } catch {
      setError('Falha ao atualizar processamento de webhooks');
      setTimeout(() => setError(''), 3000);
    }
  }

  function handleModalSuccess() {
    setSuccessMsg(vinculoEdit ? 'Vínculo atualizado com sucesso' : 'Vínculo criado com sucesso');
    carregarDados();
    setTimeout(() => setSuccessMsg(''), 3000);
  }

  // Filtrar plataformas por search term e status
  const filteredPlatforms = platforms.filter(platform => {
    // Filtro por search term
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      const matchSearch = (
        platform.nome?.toLowerCase().includes(term) ||
        platform.vinculos?.some(v =>
          v.bling_loja_id?.toString().includes(term) ||
          v.canal_nome?.toLowerCase().includes(term)
        )
      );
      if (!matchSearch) return false;
    }

    // Filtro por status
    if (filtroStatus === 'com_problemas') {
      // Mostrar apenas plataformas com órfãos ou placeholders
      const temOrfaos = platform.vinculos?.some(v =>
        !v.bling_integration_id || !v.marketplace_integration_id ||
        (v.bling_integration_id && !integracoes.find(i => i.id === v.bling_integration_id)) ||
        (v.marketplace_integration_id && !integracoes.find(i => i.id === v.marketplace_integration_id))
      );
      return temOrfaos;
    }

    if (filtroStatus === 'saudaveis') {
      // Mostrar apenas plataformas completas
      const todosCompletos = platform.vinculos?.every(v =>
        v.bling_integration_id && v.marketplace_integration_id &&
        integracoes.find(i => i.id === v.bling_integration_id)?.is_active &&
        integracoes.find(i => i.id === v.marketplace_integration_id)?.is_active
      );
      return todosCompletos;
    }

    return true;
  });

  // Calcular totais para os filtros
  const totaisStatus = React.useMemo(() => {
    let comProblemas = 0;
    let saudaveis = 0;

    platforms.forEach(platform => {
      const temProblema = platform.vinculos?.some(v =>
        !v.bling_integration_id || !v.marketplace_integration_id ||
        (v.bling_integration_id && !integracoes.find(i => i.id === v.bling_integration_id)) ||
        (v.marketplace_integration_id && !integracoes.find(i => i.id === v.marketplace_integration_id))
      );

      if (temProblema) {
        comProblemas++;
      } else {
        saudaveis++;
      }
    });

    return {
      total: platforms.length,
      comProblemas,
      saudaveis
    };
  }, [platforms, integracoes]);

  return (
    <div className="space-y-6">
      {/* Cabeçalho com título e ajuda */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold">Canais e Lojas Bling</h2>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle className="h-4 w-4 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent className="max-w-md">
                <p className="text-sm">
                  <strong>Vínculos</strong> conectam seus canais de venda às lojas no Bling e às integrações de marketplace.
                </p>
                <ul className="text-xs mt-2 space-y-1">
                  <li>• <strong>Canal de Venda:</strong> Shopee, Amazon, Mercado Livre, etc.</li>
                  <li>• <strong>Loja Bling:</strong> ID da loja conforme aparece no Bling</li>
                  <li>• <strong>Integração Bling:</strong> Conta Bling usada para API</li>
                  <li>• <strong>Integração Marketplace:</strong> Conexão com a plataforma de venda</li>
                </ul>
                <p className="text-xs mt-2 text-amber-600 font-medium">
                  ⚠️ <strong>Importante:</strong> Para importar pedidos automaticamente, você precisa vincular tanto a integração Bling quanto a do Marketplace.
                </p>
                <p className="text-xs mt-2 text-blue-600 font-medium">
                  🔑 <strong>Renovar Token:</strong> Vá para a aba "Integrações" para renovar tokens de acesso.
                </p>
                <p className="text-xs mt-2 text-muted-foreground">
                  💻 <strong>Corrigir órfãos:</strong> Execute <code className="bg-muted px-1">python scripts/fix_orphan_vinculos.py --create-dummies</code>
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>

      {/* Mensagens de Feedback */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {successMsg && (
        <Alert className="bg-green-50 border-green-200">
          <AlertDescription className="text-green-800">
            {successMsg}
          </AlertDescription>
        </Alert>
      )}

      {/* Filtros de Status */}
      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
        <Tabs value={filtroStatus} onValueChange={setFiltroStatus} className="w-full md:w-auto">
          <TabsList className="grid w-full md:w-auto grid-cols-3">
            <TabsTrigger value="todas" className="flex items-center gap-2">
              Todas ({totaisStatus.total})
            </TabsTrigger>
            <TabsTrigger value="com_problemas" className="flex items-center gap-2">
              <FileWarning className="h-4 w-4" />
              Problemas ({totaisStatus.comProblemas})
            </TabsTrigger>
            <TabsTrigger value="saudaveis" className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              Saudáveis ({totaisStatus.saudaveis})
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {/* Barra de Busca */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por plataforma, loja ou canal..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Cards de Plataformas */}
      {loading ? (
        <div className="text-center py-20">
          <div className="flex items-center justify-center gap-2 text-muted-foreground">
            <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
            <p>Carregando configurações...</p>
          </div>
        </div>
      ) : filteredPlatforms.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {filteredPlatforms.map((platform) => (
            <IntegracaoCard
              key={platform.nome}
              plataforma={platform.nome}
              vinculos={platform.vinculos}
              integracoes={integracoes.filter(i =>
                i.module_id === platform.nome.toLowerCase() ||
                platform.integrations?.includes(i.instance_name)
              )}
              canais={canais}
              onEditVinculo={handleEditVinculo}
              onDeleteVinculo={handleDeleteVinculo}
              onAddVinculo={handleAddVinculo}
              onToggleWebhooks={handleToggleWebhooks}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-20">
          <AlertCircle className="w-12 h-12 mx-auto mb-4 text-muted-foreground opacity-20" />
          <p className="text-muted-foreground">
            {searchTerm
                ? 'Nenhuma plataforma encontrada para sua busca'
                : 'Nenhuma plataforma configurada'}
            </p>
          </div>
        )}

        {/* Modal de Vínculo */}
        <VinculoModal
          open={modalOpen}
          onOpenChange={setModalOpen}
          vinculoEdit={vinculoEdit}
          plataformaFilter={plataformaFilter}
          onSuccess={handleModalSuccess}
        />
      </div>
  );
}
