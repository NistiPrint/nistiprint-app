# Gestão: consistência e recuperação de geografia

## Ordem de implantação

1. Publique a migração `20261020220000_gestao_consistency_signals.sql` e atualize API, worker de projeção e frontend na mesma implantação. A migração não altera os fatos históricos por conta própria.
2. Execute a auditoria de leitura antes do reprocessamento. Configure `NISTIPRINT_GESTAO_AUDIT_DSN` com a conexão PostgreSQL do ambiente e rode `python scripts/audit_gestao.py --start 2026-09-21 --end 2026-10-20`. O relatório contém somente agregados por dia e conta.
3. Após confirmar que o worker novo está ativo, configure `NISTIPRINT_GESTAO_REPAIR_DSN` e rode `python scripts/requeue_gestao_geography.py --account-id 7091 --max-batches 10` para o Mercado Livre. Use o `último ID` retornado como `--after` na próxima execução até que um lote enfileire zero pedidos. Repita para a conta Shopee 6, se quiser limpar o histórico de destinos mascarados. Cada lote tem no máximo 100 pedidos e não chama APIs externas.
4. Acompanhe `gestao_outbox`, horário da última projeção e `gestao_daily_dirty`. Após drenarem, repita a auditoria e compare os totais por dia e conta com o painel. A atualização pode ser vista com atraso de até 60 segundos por causa do cache.

## Interpretação

- Valor dos itens é a soma dos subtotais elegíveis. Repasse, descontos e frete não entram nessa medida.
- Destinos mascarados ou ausentes são `Não informado`; a cobertura geográfica usa pedidos elegíveis como denominador.
- O vínculo com produto interno limita custos e planejamento. Rankings por anúncio continuam disponíveis para itens sem vínculo.
- Contribuição só aparece quando repasse, custo, tributos e despesas variáveis são conhecidos. A seção financeira mostra quantos pedidos carecem de cada componente.
- Atraso observado compara horário de envio e prazo registrados. Confira a definição do prazo do marketplace antes de tratá-lo como violação de SLA.

## Verificações de aceite

- Auditoria: `item_value_mismatches = 0` e `item_count_mismatches = 0`; pedidos sem fato aparecem em `unprojected_orders` e/ou na fila.
- Painel: soma de canais e dias corresponde ao resumo para o mesmo recorte; ranking segue valor decrescente; a região apresenta ticket quando o valor é conhecido.
- Mercado Livre: destinos aparecem depois do reprocessamento dos pedidos cujo espelho traz `destination.shipping_address`; destinos mascarados da Shopee não contam como geografia conhecida.
- Cartões: cada oportunidade e exceção informa período, base, evidência e link para investigação; comparações sem histórico suficiente não são exibidas.
