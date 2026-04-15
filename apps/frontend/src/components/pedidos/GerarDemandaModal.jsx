import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

export default function GerarDemandaModal({
  open,
  onOpenChange,
  onGerarDemanda,
  quantidadePedidos,
  canalVendaId = null,
  canalVendaNome = null,
  horarioColetaInicial = '',
}) {
  const [dados, setDados] = useState({
    nome_demanda: '',
    data_entrega: new Date().toISOString().split('T')[0],
    horario_coleta: horarioColetaInicial,
    observacoes: '',
  });
  const [gerando, setGerando] = useState(false);

  // Update horario_coleta when prop changes
  useEffect(() => {
    if (horarioColetaInicial) {
      setDados(prev => ({ ...prev, horario_coleta: horarioColetaInicial }));
    }
  }, [horarioColetaInicial]);

  const handleSubmit = async () => {
    setGerando(true);
    try {
      await onGerarDemanda({
        ...dados,
        canal_venda_id: canalVendaId,
      });
    } finally {
      setGerando(false);
    }
  };

  // Auto-preencher nome da demanda
  const handleQuantidadeChange = (qtd) => {
    if (!dados.nome_demanda) {
      setDados(prev => ({
        ...prev,
        nome_demanda: `Demanda - ${qtd} pedido(s) - ${new Date().toLocaleDateString('pt-BR')}`
      }));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>📊 Gerar Demanda de Produção</DialogTitle>
          <DialogDescription>
            Crie demandas de produção para {quantidadePedidos} pedido(s) selecionado(s)
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="nome-demanda">
              Nome da Demanda
            </Label>
            <Input
              id="nome-demanda"
              value={dados.nome_demanda}
              onChange={(e) => setDados({ ...dados, nome_demanda: e.target.value })}
              placeholder="Ex: Demanda Shopee - Março"
            />
          </div>

          {canalVendaId && (
            <div className="space-y-2">
              <Label htmlFor="canal-venda">
                Canal de Venda
              </Label>
              <Input
                id="canal-venda"
                value={canalVendaNome || `Canal ID: ${canalVendaId}`}
                disabled
                className="bg-muted"
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="data-entrega">
              Data de Entrega
            </Label>
            <Input
              id="data-entrega"
              type="date"
              value={dados.data_entrega}
              onChange={(e) => setDados({ ...dados, data_entrega: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="horario-coleta">
              Horário de Coleta (Opcional)
            </Label>
            <Input
              id="horario-coleta"
              type="time"
              value={dados.horario_coleta}
              onChange={(e) => setDados({ ...dados, horario_coleta: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="observacoes">
              Observações (Opcional)
            </Label>
            <Input
              id="observacoes"
              value={dados.observacoes}
              onChange={(e) => setDados({ ...dados, observacoes: e.target.value })}
              placeholder="Ex: Urgente, entregar na portaria..."
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={gerando}
          >
            Cancelar
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={gerando || !dados.nome_demanda || !dados.data_entrega}
            className="bg-green-600 hover:bg-green-700"
          >
            {gerando ? (
              <>
                <Loader2 className="animate-spin mr-2" />
                Gerando...
              </>
            ) : (
              `Gerar Demanda (${quantidadePedidos})`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
