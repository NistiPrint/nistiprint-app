import React, { useState, useEffect } from 'react';
import IntegracaoCard from '@/components/integracoes/IntegracaoCard';
import VinculoModal from '@/components/integracoes/VinculoModal';
import * as integracaoCanalService from '@/services/integracaoCanalService';
import { Input } from '@/components/ui/input';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Search,
  AlertCircle,
  HelpCircle
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';

/**
 * Tab de Configuração de Vínculos de Canais
 * Gerencia vínculos entre canais de venda, lojas Bling e integrações
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
    } catch (err) {
      setError('Falha ao remover vínculo');
      setTimeout(() => setError(''), 3000);
    }
  }

  function handleModalSuccess() {
    setSuccessMsg(vinculoEdit ? 'Vínculo atualizado com sucesso' : 'Vínculo criado com sucesso');
    carregarDados();
    setTimeout(() => setSuccessMsg(''), 3000);
  }

  // Filtrar plataformas por search term
  const filteredPlatforms = platforms.filter(platform => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      platform.nome?.toLowerCase().includes(term) ||
      platform.vinculos?.some(v =>
        v.bling_loja_id?.toString().includes(term) ||
        v.canal_nome?.toLowerCase().includes(term)
      )
    );
  });

  return (
    <div className="space-y-6">
      {/* Cabeçalho com título e ajuda */}
      <div className="flex items-center justify-between gap-4">
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
                  ⚠️ Importante: Para importar pedidos automaticamente, você precisa vincular tanto a integração Bling quanto a do Marketplace.
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>

      {/* Barra de Busca */}
      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
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
