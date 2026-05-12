import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Clock, Package, Zap } from 'lucide-react';
import { useEffect, useState } from 'react';

export default function FiltrosContextuais({ onFiltroContextual }) {
  const [canaisProximos, setCanaisProximos] = useState([]);
  const [contagens, setContagens] = useState({});
  const [horarioAtual, setHorarioAtual] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const carregarDados = async () => {
      try {
        const [canaisRes, contagensRes] = await Promise.all([
          fetch('/api/v2/pedidos/canais-proximos-coleta'),
          fetch('/api/v2/pedidos/contagem-por-canal?dias=7'),
        ]);

        const canaisData = await canaisRes.json();
        const contagensData = await contagensRes.json();

        if (canaisData.success) {
          setCanaisProximos(canaisData.data.canais_proximos || []);
          setHorarioAtual(canaisData.data.horario_atual || '');
        }

        if (contagensData.success) {
          const contagensMap = {};
          (contagensData.data.contagens || []).forEach((c) => {
            contagensMap[c.canal_venda_id] = {
              total: c.total_pedidos,
              sem_demanda: c.pedidos_sem_demanda,
              com_demanda: c.pedidos_com_demanda,
            };
          });
          setContagens(contagensMap);
        }
      } catch (error) {
        console.error('Erro ao carregar filtros contextuais:', error);
      } finally {
        setLoading(false);
      }
    };

    carregarDados();
  }, []);

  const handleFiltrarCanal = (canal) => {
    onFiltroContextual?.({
      tipo: 'canal',
      canal_venda_id: canal.id,
      canal_nome: canal.nome,
    });
  };

  const handleFiltrarFlex = (canal) => {
    onFiltroContextual?.({
      tipo: 'flex',
      canal_venda_id: canal.id,
      canal_nome: canal.nome,
    });
  };

  const handleFiltrarSemDemanda = (canal) => {
    onFiltroContextual?.({
      tipo: 'sem_demanda',
      canal_venda_id: canal.id,
      canal_nome: canal.nome,
    });
  };

  if (loading) {
    return (
      <Card className="mb-4">
        <CardContent className="py-4">
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
            <Clock className="h-4 w-4 animate-pulse" />
            <span>Carregando proximas coletas...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (canaisProximos.length === 0) {
    return (
      <Card className="mb-4 border-dashed">
        <CardContent className="py-4">
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
            <Clock className="h-4 w-4" />
            <span>
              Nenhuma origem com horario de coleta configurado. Configure em{' '}
              <a href="/cadastros/canal-venda" className="text-primary underline">
                Origens da venda
              </a>
            </span>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mb-4">
      <CardContent className="py-4">
        <div className="flex items-center gap-2 mb-3">
          <Clock className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">Proximas coletas</span>
          {horarioAtual && (
            <Badge variant="outline" className="text-xs">
              {horarioAtual}
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {canaisProximos.map((canal, index) => {
            const contagem = contagens[canal.id];
            const semDemanda = contagem?.sem_demanda || 0;

            return (
              <div
                key={canal.id}
                className={`flex items-center gap-2 p-3 rounded-md border transition-all ${
                  index === 0
                    ? 'border-orange-300 bg-orange-50'
                    : 'border-border bg-muted/50'
                }`}
                style={{
                  borderLeftColor: canal.color || undefined,
                  borderLeftWidth: canal.color ? '3px' : undefined,
                }}
              >
                {index === 0 && (
                  <Badge className="bg-orange-500 text-white text-xs h-5">
                    <Zap className="h-3 w-3 mr-0.5" />
                    Proxima
                  </Badge>
                )}

                <div className="flex items-center gap-2">
                  <div className="text-sm">
                    <span className="font-medium">{canal.nome}</span>
                    <span className="text-muted-foreground mx-1">-</span>
                    <span className="text-orange-600 font-medium">
                      {canal.horario_coleta || '--:--'}
                    </span>
                  </div>

                  {canal.flex && (
                    <Badge variant="secondary" className="bg-orange-100 text-orange-700 border-orange-300 h-5 text-xs">
                      <Zap className="h-3 w-3 mr-0.5" />
                      Flex
                    </Badge>
                  )}

                  {semDemanda > 0 && (
                    <Badge variant="secondary" className="bg-red-100 text-red-700 border-red-300 h-5 text-xs">
                      {semDemanda} a produzir
                    </Badge>
                  )}
                </div>

                <div className="flex items-center gap-1 ml-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => handleFiltrarCanal(canal)}
                  >
                    Filtrar
                  </Button>

                  {canal.flex && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs bg-orange-50 hover:bg-orange-100 text-orange-700 border-orange-300"
                      onClick={() => handleFiltrarFlex(canal)}
                    >
                      <Zap className="h-3 w-3" />
                    </Button>
                  )}

                  {semDemanda > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs bg-red-50 hover:bg-red-100 text-red-700 border-red-300"
                      onClick={() => handleFiltrarSemDemanda(canal)}
                    >
                      <Package className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
