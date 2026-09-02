import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AlertTriangle, FileText, Package, RotateCcw, X } from 'lucide-react';
import { Fragment } from 'react';

// A consolidação de um lote — a mesma tabela, venha ela da prévia ou da demanda
// já materializada.
//
// Contrato: docs/specs/02-domains/despacho/spec.md
//
// A ordem É a informação: miolo com mais carga primeiro e, dentro do miolo,
// quantidade decrescente. É a ordem em que a fábrica produz, e é a mesma da
// planilha do legado. Ela vem pronta do banco (`despacho_consolidar_pedidos`,
// via `ordem`) e NÃO deve ser reordenada aqui — reordenar no cliente criaria
// uma segunda opinião sobre a ordem de produção.
//
// `contabiliza_estoque` falso não é pendência nem erro: a linha produz
// normalmente, só não movimenta estoque, porque o SKU do marketplace não tem
// produto interno vinculado. Aparece como aviso e com caminho para o cadastro,
// nunca como bloqueio — a regra do domínio é degradar, não reter.
//
// MODO EDIÇÃO (`onAjustar` presente): o operador corrige a lista antes de
// publicar — remove uma linha, ajusta uma quantidade. É a saída para o que
// NÃO está cadastrado: kit cadastrado já chega aqui explodido nos produtos que
// o compõem (`despacho_consolidar_pedidos`), e não depende de ninguém clicar.
// O componente não decide nada: emite a operação, e quem grava é a página. A
// conta que aparece aqui é a MESMA que `despacho_materializar_itens` refaz no
// servidor, que é quem vale.
//
// Linha com selo "kit" é, por definição, um kit SEM ficha técnica válida — se
// tivesse, teria sido explodida antes de chegar na tela. O selo é o aviso de
// lacuna de cadastro, não um botão.

function agruparPorMiolo(itens) {
  // Agrupa preservando a ordem que veio do banco, em vez de ordenar por chave:
  // itens do mesmo miolo já chegam adjacentes, e qualquer reordenação aqui
  // desmancharia o ranking por carga.
  const grupos = [];
  for (const item of itens) {
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.chave === item.miolo_chave) ultimo.itens.push(item);
    else grupos.push({ chave: item.miolo_chave, rotulo: item.miolo_nome, itens: [item] });
  }
  return grupos;
}

const inteiro = (valor) => Math.round(Number(valor || 0));

export default function LinhasConsolidadas({
  itens = [],
  resumo = null,
  titulo = 'Ordem de produção',
  ajuda = 'miolo com mais carga primeiro',
  rotuloDemanda = null,
  carregando = false,
  erro = null,
  className = 'mb-6',
  // Edição da prévia. Sem `onAjustar` a tabela é só leitura, como sempre foi.
  onAjustar = null,
  totalAjustes = 0,
  onDesfazerAjustes = null,
}) {
  const editavel = typeof onAjustar === 'function';
  if (erro) {
    return (
      <Card className={`border-destructive/50 ${className}`}>
        <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
      </Card>
    );
  }

  if (carregando) {
    return <div className={`h-32 w-full animate-pulse rounded-md bg-muted ${className}`} />;
  }

  const grupos = agruparPorMiolo(itens);
  const totalPecas = resumo?.total_pecas ?? itens.reduce((s, i) => s + Number(i.quantidade || 0), 0);
  const totalMiolos = resumo?.total_miolos ?? grupos.length;
  const semEstoque = resumo?.sem_estoque ?? itens.filter((i) => !i.contabiliza_estoque).length;

  if (!itens.length) {
    return (
      <Card className={`border-dashed ${className}`}>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          {totalAjustes > 0
            ? 'Os ajustes removeram todas as linhas do lote.'
            : 'Nenhum item para consolidar. Os pedidos deste lote ainda não têm itens registrados na base.'}
          {totalAjustes > 0 && onDesfazerAjustes && (
            <div className="mt-3">
              <Button size="sm" variant="outline" onClick={onDesfazerAjustes}>
                <RotateCcw className="mr-2 h-3.5 w-3.5" /> Desfazer os ajustes
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium">{titulo}</span>
        {ajuda && <span className="text-xs text-muted-foreground">{ajuda}</span>}
        <span className="ml-auto text-xs text-muted-foreground">
          <FileText className="mr-1 inline h-3.5 w-3.5" />
          {rotuloDemanda ? `${rotuloDemanda} · ` : ''}
          {itens.length} linhas · {inteiro(totalPecas)} peças · {totalMiolos}{' '}
          {totalMiolos === 1 ? 'miolo' : 'miolos'}
        </span>
      </div>

      {totalAjustes > 0 && (
        <div className="mb-2 flex items-center gap-2 rounded-md border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-xs text-sky-800">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {totalAjustes === 1 ? '1 ajuste manual' : `${totalAjustes} ajustes manuais`} nesta
          lista — o lote será publicado como está abaixo.
          {onDesfazerAjustes && (
            <button
              type="button"
              onClick={onDesfazerAjustes}
              className="ml-auto inline-flex items-center gap-1 font-medium underline underline-offset-2"
            >
              <RotateCcw className="h-3 w-3" /> desfazer tudo
            </button>
          )}
        </div>
      )}

      {semEstoque > 0 && (
        <div className="mb-2 flex items-center gap-1.5 text-xs text-amber-700">
          <AlertTriangle className="h-3 w-3 shrink-0" />
          {semEstoque} {semEstoque === 1 ? 'linha produz' : 'linhas produzem'} sem movimentar
          estoque — o SKU do marketplace ainda não tem produto interno vinculado.
        </div>
      )}

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Produto</th>
              <th className="px-3 py-2 font-medium">Variação</th>
              <th className="px-3 py-2 font-medium">SKU</th>
              <th className="px-3 py-2 font-medium">Produto interno</th>
              <th className="w-20 px-3 py-2 text-right font-medium">Qtde</th>
              {editavel && <th className="w-24 px-3 py-2 font-medium" />}
            </tr>
          </thead>
          <tbody>
            {grupos.map((grupo, indice) => {
              const carga = grupo.itens.reduce((s, i) => s + Number(i.quantidade || 0), 0);
              // `miolo_origem` distingue o miolo que veio da ficha técnica do
              // que foi derivado do prefixo do SKU. São confianças diferentes:
              // o primeiro é cadastro, o segundo é convenção de nomenclatura.
              const viaBom = grupo.itens[0]?.miolo_origem === 'BOM';
              return (
                <Fragment key={grupo.chave ?? `miolo-${indice}`}>
                  <tr className="border-t bg-muted/30">
                    <td colSpan={editavel ? 6 : 5} className="px-3 py-1.5 text-xs font-semibold">
                      <span className="inline-flex items-center gap-1.5">
                        <Package className="h-3.5 w-3.5" />
                        Miolo {grupo.rotulo || grupo.chave || 'não identificado'}
                        {viaBom && (
                          <Badge variant="outline" className="text-[9px]">via ficha técnica</Badge>
                        )}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right text-xs font-semibold tabular-nums">
                      {inteiro(carga)}
                    </td>
                  </tr>
                  {grupo.itens.map((item, linha) => (
                    <tr key={item.id ?? `${grupo.chave}-${item.sku_externo}-${linha}`} className="border-t">
                      <td className="px-3 py-2 text-xs tabular-nums text-muted-foreground">
                        {item.ordem}
                      </td>
                      <td className="px-3 py-2">
                        {item.descricao || '—'}
                        {item.eh_kit && (
                          <Badge
                            variant="outline"
                            className="ml-2 border-amber-400 text-[9px] text-amber-700"
                            title="Kit sem produtos acabados na ficha técnica — cadastre a ficha para ele passar a explodir sozinho"
                          >
                            kit sem ficha
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.variacao && item.variacao !== '-' ? item.variacao : '—'}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                        {item.sku_externo || '—'}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {item.contabiliza_estoque ? (
                          <span className="text-muted-foreground">
                            {item.produto_nome || `#${item.produto_id}`}
                          </span>
                        ) : (
                          // Não é um controle de vínculo: vincular produto é
                          // cadastro, e é lá que a decisão persiste. Um seletor
                          // aqui salvaria no nada — foi o que a tela antiga fazia.
                          <Badge variant="outline" className="border-amber-400 text-[10px] text-amber-700">
                            sem vínculo
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {editavel ? (
                          <Input
                            type="number"
                            min="1"
                            className="h-8 w-20 text-right tabular-nums"
                            value={inteiro(item.quantidade)}
                            onChange={(evento) => {
                              const valor = Math.round(Number(evento.target.value));
                              if (!Number.isFinite(valor) || valor < 1) return;
                              if (valor === inteiro(item.quantidade)) return;
                              onAjustar({ op: 'quantidade', linha: item, valor });
                            }}
                          />
                        ) : (
                          inteiro(item.quantidade)
                        )}
                      </td>
                      {editavel && (
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                              title="Remover esta linha do lote"
                              onClick={() => onAjustar({ op: 'remover', linha: item })}
                            >
                              <X className="h-4 w-4" />
                            </Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
