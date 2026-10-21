"""Explain commercial opportunities and exceptions from bounded report aggregates."""

from urllib.parse import urlencode


def _link(area, report, filters, **extra):
    query = {'start': report['period']['start'], 'end': report['period']['end'],
             **{k: v for k, v in filters.items() if v not in (None, '')}, **extra}
    return f'/gestao/{area}?{urlencode(query)}'


def _card(key, title, evidence, action, href, *, impact=None, confidence='observado'):
    return {'id': key, 'title': title, 'evidence': evidence, 'action': action,
            'href': href, 'impact': impact, 'confidence': confidence}


def _money(value):
    return f'R$ {value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def build_signals(report, filters):
    """Return only claims supported by the current period and its known coverage."""
    summary, previous = report['summary'], report['previous']
    quality = report['quality']
    opportunities, exceptions = [], []
    comparable = report.get('changes', {}).get('sales') is not None
    product_url = _link('produtos', report, filters)
    sales_url = _link('vendas', report, filters)
    quality_url = _link('qualidade', report, filters)

    if comparable:
        for row in report.get('product_movements') or []:
            current, old = row.get('current_sales'), row.get('previous_sales')
            if current is None or old is None or old <= 0:
                continue
            if min(row['current_orders'], row['previous_orders']) < 10:
                continue
            delta = float(current) - float(old)
            change = 100 * delta / float(old)
            if abs(change) < 25 or abs(delta) < 300:
                continue
            extra = {'product_id': row['product_id']} if row.get('product_id') else {'account_id': row['account_id']}
            href = _link('produtos', report, filters, **extra)
            label = row.get('name') or row['key']
            evidence = (f'{row["current_orders"]} pedidos e {_money(current)} neste período; '
                        f'{row["previous_orders"]} pedidos e {_money(old)} no anterior '
                        f'({change:+.1f}%).')
            if delta > 0:
                opportunities.append(_card(f'product_growth:{row["key"]}', f'Produto em crescimento: {label}',
                    evidence, 'Confira disponibilidade e desempenho dos anúncios antes de ampliar a oferta.',
                    href, impact=round(delta, 2)))
            else:
                exceptions.append(_card(f'product_drop:{row["key"]}', f'Queda em produto: {label}',
                    evidence, 'Investigue preço, exposição, disponibilidade e estados dos pedidos.',
                    href, impact=round(-delta, 2)))

        for row in report.get('channel_movements') or []:
            current, old = row['current_stats'], row['previous_stats']
            if min(current['orders'], old['orders']) < 10 or current['sales'] is None or not old['sales']:
                continue
            delta = float(current['sales']) - float(old['sales'])
            change = 100 * delta / float(old['sales'])
            if abs(change) < 25 or abs(delta) < 300:
                continue
            href = _link('vendas', report, filters, account_id=row['account_id'])
            evidence = (f'{current["orders"]} pedidos e {_money(current["sales"])} neste período; '
                        f'{old["orders"]} pedidos e {_money(old["sales"])} no anterior ({change:+.1f}%).')
            if delta > 0:
                opportunities.append(_card(f'channel_growth:{row["account_id"]}',
                    f'Canal em crescimento: {row["marketplace"]}', evidence,
                    'Confira os produtos responsáveis e a capacidade de atendimento.', href, impact=round(delta, 2)))
            else:
                exceptions.append(_card(f'channel_drop:{row["account_id"]}',
                    f'Queda no canal: {row["marketplace"]}', evidence,
                    'Verifique anúncios, cancelamentos, cobertura e integração da conta.', href, impact=round(-delta, 2)))

        if report['changes']['sales'] <= -20:
            exceptions.append(_card('sales_drop', 'Queda no valor dos itens',
                f'{report["changes"]["sales"]:+.1f}% em períodos comparáveis.',
                'Investigue canais e produtos antes de rever campanhas.', sales_url))
        if min(summary['created'], previous['created']) >= 10 and summary['cancel_rate'] is not None \
                and previous['cancel_rate'] is not None and summary['cancel_rate']-previous['cancel_rate'] >= 5:
            exceptions.append(_card('cancellations', 'Aumento de cancelamentos',
                f'{summary["cancelled"]}/{summary["created"]} pedidos ({summary["cancel_rate"]:.1f}%), '
                f'contra {previous["cancel_rate"]:.1f}% no período anterior.',
                'Investigue motivos, produtos e prazos por canal.', sales_url))

    for row in report.get('planning') or []:
        if row.get('product_id') and row.get('available') is not None and row.get('daily_units') \
                and row.get('coverage_days') is not None and row['coverage_days'] < 7 \
                and row.get('suggested_units', 0) > 0:
            opportunities.append(_card(f'stock:{row["product_id"]}',
                f'Demanda acima do estoque: {row["name"]}',
                f'{row["coverage_days"]} dias de cobertura; faltam cerca de {row["suggested_units"]} unidades para sete dias.',
                'Confirme o saldo e programe reposição ou produção.',
                _link('planejamento', report, filters, product_id=row['product_id']),
                impact=row['suggested_units'], confidence='estimativa'))

    operations = report.get('operations') or {}
    observed = operations.get('observed_dispatches') or 0
    late = operations.get('late_dispatches') or 0
    if observed >= 20 and late / observed >= .10:
        exceptions.append(_card('late_dispatch', 'Despachos após o prazo registrado',
            f'{late}/{observed} despachos observados ({100*late/observed:.1f}%).',
            'Confira a definição do prazo e os pedidos antes de alterar o fluxo operacional.',
            _link('planejamento', report, filters), confidence='verificar_prazo'))
    if summary.get('unknown'):
        exceptions.append(_card('unknown_stage', 'Estados comerciais não classificados',
            f'{summary["unknown"]}/{summary["created"]} pedidos do recorte.',
            'Revise a classificação por canal para recuperar as vendas elegíveis.', quality_url))
    items = quality.get('items') or 0
    mapped = quality.get('mapped_items') or 0
    if items and mapped / items < .8:
        exceptions.append(_card('product_mapping', 'Poucos itens vinculados ao catálogo',
            f'{mapped}/{items} itens ({100*mapped/items:.1f}%) com produto interno.',
            'Vincule primeiro os anúncios de maior valor; planejamento e custo dependem dessa associação.',
            product_url))
    if quality.get('masked_geography'):
        exceptions.append(_card('masked_geography', 'Destinos mascarados pela plataforma',
            f'{quality["masked_geography"]} pedidos com estado mascarado no recorte.',
            'Trate esses destinos como indisponíveis nas análises regionais.',
            _link('publico', report, filters)))
    products = report.get('products') or []
    if products and (summary.get('sales_coverage') or 0) >= 95:
        leader = max(products, key=lambda row: row.get('sales') or 0)
        if (leader.get('share') or 0) >= 40 and (leader.get('orders') or 0) >= 10:
            exceptions.append(_card('product_concentration', 'Vendas concentradas em um produto ou anúncio',
                f'{leader.get("name") or leader["key"]}: {leader["share"]:.1f}% do valor dos itens em '
                f'{leader["orders"]} pedidos.',
                'Confira disponibilidade, dependência do anúncio e alternativas no catálogo.', product_url))
    if report.get('projection_pending'):
        exceptions.append(_card('projection_pending', 'Atualização analítica pendente',
            f'{report["projection_pending"]} pedidos aguardam projeção.',
            'Verifique a fila de Gestão e o horário da última atualização.', quality_url))
    gaps = report.get('finance_gaps')
    if gaps and gaps.get('orders') and ((report.get('profitability') or {}).get('coverage') or 0) < 80:
        exceptions.append(_card('finance_gap', 'Rentabilidade com dados incompletos',
            f'{gaps["missing_payout"]} sem repasse, {gaps["missing_product_cost"]} sem custo, '
            f'{gaps["missing_taxes"]} sem tributos e {gaps["missing_operating_cost"]} sem despesas '
            f'entre {gaps["orders"]} pedidos elegíveis.',
            'Complete e concilie os componentes antes de usar margem para decidir preços.',
            _link('rentabilidade', report, filters)))

    opportunities.sort(key=lambda c: c['impact'] or 0, reverse=True)
    priority = {'finance_gap': 0, 'late_dispatch': 1, 'product_mapping': 2,
                'masked_geography': 3, 'unknown_stage': 4, 'projection_pending': 5,
                'cancellations': 6, 'sales_drop': 7, 'product_concentration': 8}
    exceptions.sort(key=lambda c: (priority.get(c['id'], 8), -(c['impact'] or 0)))
    return opportunities[:8], exceptions[:12]
