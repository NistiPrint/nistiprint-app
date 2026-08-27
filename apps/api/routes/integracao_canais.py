"""
Endpoints para gerenciamento de vínculos entre canais de venda, lojas Bling e integrações.

Rotas:
    GET    /api/integracao-canais/configuracoes          - Listar configurações
    POST   /api/integracao-canais/configuracoes          - Criar vínculo
    PUT    /api/integracao-canais/configuracoes/<id>     - Atualizar vínculo
    DELETE /api/integracao-canais/configuracoes/<id>     - Remover vínculo
    GET    /api/integracao-canais/resolver/canal         - Resolver canal por bling_loja_id
    GET    /api/integracao-canais/resolver/bling-loja    - Resolver bling_loja_id por canal
"""

from flask import request, Blueprint, jsonify
from routes.auth import login_required
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.services.marketplace_account_identity import has_account_identity
from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
import logging

logger = logging.getLogger("IntegracaoCanaisAPI")

integracao_canais_bp = Blueprint('integracao_canais', __name__, url_prefix='/api/v2/integracao-canais')


def _get_installed_integration_row(integration_id):
    if not integration_id:
        return None
    result = (
        supabase_db.table('installed_integrations')
        .select('id,module_id,instance_name,instance_color,config,credentials,is_active')
        .eq('id', integration_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _merge_ingest_origin_mode(data):
    config_json = dict(data.get('config_json') or {})
    if data.get('ingest_origin_mode'):
        config_json['ingest_origin_mode'] = data.get('ingest_origin_mode')
    return config_json


def _hydrate_channel_fields_from_integration(data):
    if data.get('canal_venda_id') and data.get('plataforma_nome'):
        return data

    integration_id = data.get('marketplace_integration_id') or data.get('integration_id')
    integration = _get_installed_integration_row(integration_id)
    if not integration or integration.get('module_id') == 'bling':
        return data

    module_id = integration.get('module_id')
    platform_rows = (
        supabase_db.client.table('plataformas')
        .select('id,nome')
        .ilike('nome', f"%{module_id}%")
        .limit(1)
        .execute()
        .data
        or []
    )
    platform = platform_rows[0] if platform_rows else None
    platform_name = platform.get('nome') if platform else module_id

    if not data.get('plataforma_nome'):
        data['plataforma_nome'] = platform_name

    if data.get('canal_venda_id'):
        return data

    channel_name = integration.get('instance_name') or f"{platform_name} {integration_id}"
    channel_rows = (
        supabase_db.client.table('canais_venda')
        .select('id')
        .eq('nome', channel_name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if channel_rows:
        data['canal_venda_id'] = channel_rows[0]['id']
        return data

    insert_payload = {
        'nome': channel_name,
        'slug': f"{module_id}-{integration_id}",
        'ativo': True,
        'color': integration.get('instance_color') or '#64748b',
    }
    if platform:
        insert_payload['plataforma_id'] = platform['id']

    inserted = supabase_db.client.table('canais_venda').insert(insert_payload).execute().data
    if inserted:
        data['canal_venda_id'] = inserted[0]['id']
    return data


def _marketplace_direct_identity_error(marketplace_integration_id):
    row = _get_installed_integration_row(marketplace_integration_id)
    if not row:
        return 'Integracao de marketplace nao encontrada para ativar marketplace_direct'
    if row.get('module_id') == 'bling':
        return 'marketplace_direct exige uma integracao de marketplace, nao uma integracao ERP'
    if not has_account_identity(row):
        return 'Configure o identificador da conta no marketplace antes de ativar marketplace_direct'
    return None


@integracao_canais_bp.route('/configuracoes', methods=['GET'])
@login_required
def listar_configuracoes():
    """
    Lista todas as configurações de vínculos.
    
    Query params:
        plataforma: Filtrar por plataforma (shopee, amazon, etc.)
        canal_venda_id: Filtrar por canal específico
        include_inactive: Incluir configurações inativas (true/false)
    """
    try:
        plataforma = request.args.get('plataforma')
        canal_venda_id = request.args.get('canal_venda_id')
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        
        if canal_venda_id:
            canal_venda_id = int(canal_venda_id)
        
        configs = integracao_canal_service.listar_configuracoes(
            plataforma_nome=plataforma,
            canal_venda_id=canal_venda_id,
            include_inactive=include_inactive
        )
        
        return jsonify({
            'success': True,
            'data': configs,
            'count': len(configs)
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar configurações: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/configuracoes', methods=['POST'])
@login_required
def criar_vinculo():
    """
    Cria novo vínculo entre canal e loja Bling.
    
    Payload:
        {
            "canal_venda_id": 1,
            "bling_loja_id": 204047801,
            "plataforma_nome": "Shopee",
            "integration_id": 6,  // opcional
            "is_primary": true,
            "config_json": {}  // opcional
        }
    """
    try:
        data = request.get_json()
        data = _hydrate_channel_fields_from_integration(data)
        
        # Validações básicas
        required_fields = ['canal_venda_id', 'bling_loja_id', 'plataforma_nome']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Campo obrigatório: {field}'
                }), 400
        
        # Verificar se já existe vínculo
        if data.get('bling_integration_id'):
            existing = integracao_canal_service.resolver_por_bling_integration_e_loja(
                data['bling_integration_id'],
                data['bling_loja_id'],
            )
        else:
            existing = integracao_canal_service.get_canal_by_bling_loja_id(data['bling_loja_id'])
        existing_channel_id = existing.get('canal_venda_id') or existing.get('channel_id') if existing else None
        if existing and existing_channel_id == data['canal_venda_id']:
            return jsonify({
                'success': False,
                'error': 'Já existe um vínculo para este canal e loja Bling'
            }), 409
        
        config_json = _merge_ingest_origin_mode(data)
        if config_json.get('ingest_origin_mode') == 'marketplace_direct':
            identity_error = _marketplace_direct_identity_error(
                data.get('marketplace_integration_id') or data.get('integration_id')
            )
            if identity_error:
                return jsonify({'success': False, 'error': identity_error}), 400

        config = integracao_canal_service.criar_vinculo(
            canal_venda_id=data['canal_venda_id'],
            bling_loja_id=data['bling_loja_id'],
            plataforma_nome=data['plataforma_nome'],
            integration_id=data.get('integration_id'),
            bling_integration_id=data.get('bling_integration_id'),
            marketplace_integration_id=data.get('marketplace_integration_id'),
            is_primary=data.get('is_primary', False),
            process_webhooks=data.get('process_webhooks', True),
            config_json=config_json
        )
        
        if config:
            return jsonify({
                'success': True,
                'data': config,
                'message': 'Vínculo criado com sucesso'
            }), 201
        else:
            return jsonify({
                'success': False,
                'error': 'Falha ao criar vínculo'
            }), 500
        
    except Exception as e:
        logger.error(f"Erro ao criar vínculo: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/configuracoes/<config_id>', methods=['PUT'])
@login_required
def atualizar_vinculo(config_id):
    """
    Atualiza vínculo existente.
    
    Payload:
        {
            "canal_venda_id": 1,  // opcional
            "bling_loja_id": 204047801,  // opcional
            "plataforma_nome": "Shopee",  // opcional
            "integration_id": 6,  // opcional
            "is_primary": true,  // opcional
            "is_active": true,  // opcional
            "config_json": {}  // opcional
        }
    """
    try:
        data = request.get_json()
        
        # Verificar se configuração existe
        existing = integracao_canal_service.get_config_by_id(config_id)
        if not existing:
            return jsonify({
                'success': False,
                'error': 'Configuração não encontrada'
            }), 404
        
        # Campos permitidos para atualização
        allowed_fields = ['canal_venda_id', 'bling_loja_id', 'plataforma_nome',
                         'integration_id', 'bling_integration_id', 'marketplace_integration_id',
                         'is_primary', 'is_active', 'process_webhooks', 'config_json',
                         'ingest_origin_mode']
        updates = {k: v for k, v in data.items() if k in allowed_fields}
        if data.get('ingest_origin_mode') == 'marketplace_direct':
            marketplace_integration_id = (
                data.get('marketplace_integration_id')
                or existing.get('marketplace_integration_id')
                or data.get('integration_id')
                or existing.get('integration_id')
            )
            identity_error = _marketplace_direct_identity_error(marketplace_integration_id)
            if identity_error:
                return jsonify({'success': False, 'error': identity_error}), 400
        
        config = integracao_canal_service.atualizar_vinculo(config_id, updates)
        
        if config:
            return jsonify({
                'success': True,
                'data': config,
                'message': 'Vínculo atualizado com sucesso'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Falha ao atualizar vínculo'
            }), 500
        
    except Exception as e:
        logger.error(f"Erro ao atualizar vínculo {config_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/configuracoes/<config_id>', methods=['DELETE'])
@login_required
def remover_vinculo(config_id):
    """
    Remove vínculo (soft delete).
    """
    try:
        # Verificar se configuração existe
        existing = integracao_canal_service.get_config_by_id(config_id)
        if not existing:
            return jsonify({
                'success': False,
                'error': 'Configuração não encontrada'
            }), 404
        
        success = integracao_canal_service.remover_vinculo(config_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Vínculo removido com sucesso'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Falha ao remover vínculo'
            }), 500
        
    except Exception as e:
        logger.error(f"Erro ao remover vínculo {config_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/resolver/canal', methods=['GET'])
@login_required
def resolver_canal():
    """
    Resolve qual canal usar baseado no bling_loja_id.
    
    Query params:
        bling_loja_id: ID da loja no Bling (obrigatório)
        plataforma: Nome da plataforma (opcional, para fallback)
    """
    try:
        bling_loja_id = request.args.get('bling_loja_id')
        plataforma = request.args.get('plataforma')
        
        if not bling_loja_id:
            return jsonify({
                'success': False,
                'error': 'Parâmetro bling_loja_id é obrigatório'
            }), 400
        
        result = integracao_canal_service.resolver_canal_para_pedido(
            bling_loja_id=int(bling_loja_id),
            plataforma_nome=plataforma
        )
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Erro ao resolver canal: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/resolver/bling-loja', methods=['GET'])
@login_required
def resolver_bling_loja():
    """
    Resolve qual bling_loja_id usar baseado no canal.
    
    Query params:
        canal_venda_id: ID do canal de venda (obrigatório)
        plataforma: Nome da plataforma (opcional)
    """
    try:
        canal_venda_id = request.args.get('canal_venda_id')
        plataforma = request.args.get('plataforma')
        
        if not canal_venda_id:
            return jsonify({
                'success': False,
                'error': 'Parâmetro canal_venda_id é obrigatório'
            }), 400
        
        bling_loja_id = integracao_canal_service.get_bling_loja_id_by_canal(
            canal_venda_id=int(canal_venda_id),
            plataforma_nome=plataforma
        )
        
        return jsonify({
            'success': True,
            'data': {
                'canal_venda_id': int(canal_venda_id),
                'bling_loja_id': bling_loja_id,
                'plataforma': plataforma
            }
        })
        
    except Exception as e:
        logger.error(f"Erro ao resolver bling_loja_id: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/plataformas', methods=['GET'])
@login_required
def listar_plataformas():
    """
    Lista todas as plataformas disponíveis com suas configurações.
    """
    try:
        # Buscar configurações agrupadas por plataforma
        configs = integracao_canal_service.listar_configuracoes()

        # Agrupar por plataforma
        plataformas = {}
        for config in configs:
            plataforma = config.get('plataforma_nome', 'unknown')
            if plataforma not in plataformas:
                plataformas[plataforma] = {
                    'nome': plataforma,
                    'vinculos': [],
                    'canais': set(),
                    'integrations': set()
                }

            plataformas[plataforma]['vinculos'].append({
                'id': config['id'],
                'canal_nome': config.get('canal_nome'),
                'canal_slug': config.get('canal_slug'),
                'bling_loja_id': config['bling_loja_id'],
                'is_primary': config.get('is_primary', False),
                'is_active': config.get('is_active', True),
                'process_webhooks': config.get('process_webhooks', True),
                'integration_instance': config.get('integration_instance_name'),
                # Novos campos para bling_integration e marketplace_integration
                'bling_integration_id': config.get('bling_integration_id'),
                'marketplace_integration_id': config.get('marketplace_integration_id'),
                'bling_integration': config.get('bling_integration'),
                'marketplace_integration': config.get('marketplace_integration'),
            })

            if config.get('canal_slug'):
                plataformas[plataforma]['canais'].add(config['canal_slug'])
            if config.get('integration_instance_name'):
                plataformas[plataforma]['integrations'].add(config['integration_instance_name'])

        # Converter sets para listas para JSON serialization
        for plataforma in plataformas:
            plataformas[plataforma]['canais'] = list(plataformas[plataforma]['canais'])
            plataformas[plataforma]['integrations'] = list(plataformas[plataforma]['integrations'])
            plataformas[plataforma]['total_vinculos'] = len(plataformas[plataforma]['vinculos'])
            plataformas[plataforma]['vinculos_ativos'] = sum(1 for v in plataformas[plataforma]['vinculos'] if v['is_active'])

        return jsonify({
            'success': True,
            'data': list(plataformas.values())
        })

    except Exception as e:
        logger.error(f"Erro ao listar plataformas: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/canais', methods=['GET'])
@login_required
def listar_canais_venda():
    """
    Lista todos os canais de venda disponíveis.
    Endpoint auxiliar para a tela de vínculos.
    """
    try:
        from nistiprint_shared.services.canal_venda_service import canal_venda_service
        from nistiprint_shared.services.conta_bling_service import conta_bling_service
        
        canais = canal_venda_service.get_all(active_only=False)
        contas_bling = conta_bling_service.get_all()
        
        return jsonify({
            'success': True,
            'data': canais,
            'contas_bling': contas_bling
        })
    except Exception as e:
        logger.error(f"Erro ao listar canais: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/integracoes', methods=['GET'])
@login_required
def listar_integracoes_instaladas():
    """
    Lista todas as integrações instaladas.
    Endpoint auxiliar para a tela de vínculos.
    """
    try:
        result = supabase_db.table('installed_integrations').select('*').eq('is_active', True).execute()

        return jsonify({
            'success': True,
            'data': result.data or []
        })
    except Exception as e:
        logger.error(f"Erro ao listar integrações: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/analise-status', methods=['GET'])
@login_required
def analisar_status_vinculos():
    """
    Retorna análise completa dos vínculos com status detalhado.

    Retorna:
        {
            "completos": [...],
            "incompletos": [...],
            "orfaos": [...],
            "placeholders": [...]
        }
    """
    try:
        analise = integracao_canal_service.analisar_vinculos_com_status()

        return jsonify({
            'success': True,
            'data': analise
        })
    except Exception as e:
        logger.error(f"Erro ao analisar status dos vínculos: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/plataformas-com-status', methods=['GET'])
@login_required
def listar_plataformas_com_status():
    """
    Lista plataformas com status detalhado de cada vínculo.
    Similar a /plataformas, mas inclui informações de saúde do vínculo.
    """
    try:
        plataformas = integracao_canal_service.get_vinculos_por_plataforma_com_status()

        return jsonify({
            'success': True,
            'data': plataformas
        })
    except Exception as e:
        logger.error(f"Erro ao listar plataformas com status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@integracao_canais_bp.route('/importar-pedidos-em-andamento', methods=['POST'])
@login_required
def importar_pedidos_em_andamento():
    """
    Dispara importação manual de pedidos Em Andamento do Bling para o core.
    Por padrão enfileira Celery; use async=false para execução síncrona (pode demorar).
    """
    try:
        from nistiprint_shared.services.celery_app import celery_app
        from nistiprint_shared.services.pedidos_bling_import_service import run_fetch_pedidos_em_andamento

        data = request.get_json() or {}
        config_id = data.get('config_id')
        dias = data.get('dias')
        # Aceita situacao_id ou id_situacao (para compatibilidade com exemplo do usuário)
        situacao_id = int(data.get('situacao_id') or data.get('id_situacao') or 15)
        
        data_inicial = data.get('data_inicial') or data.get('dataInicial')
        data_final = data.get('data_final') or data.get('dataFinal')
        
        async_flag = data.get('async', True)
        if isinstance(async_flag, str):
            async_flag = async_flag.lower() in ('true', '1', 'yes')

        # Se não houver config_id, mas houver id_loja, tentar resolver config_id
        if not config_id and data.get('id_loja'):
            id_loja = int(data.get('id_loja'))
            res = integracao_canal_service.get_config_by_bling_loja_id(id_loja)
            if res:
                config_id = res['id']

        if async_flag:
            celery_app.send_task(
                'tasks.pedidos_fetch_tasks.fetch_pedidos_em_andamento',
                kwargs={
                    'config_id': config_id,
                    'dias': dias,
                    'situacao_id': situacao_id,
                    'data_inicial': data_inicial,
                    'data_final': data_final
                }
            )
            return jsonify({
                'success': True,
                'queued': True,
                'message': 'Importação enfileirada. Acompanhe os logs do worker.'
            })

        result = run_fetch_pedidos_em_andamento(
            config_id=config_id,
            dias=dias,
            situacao_id=situacao_id,
            data_inicial=data_inicial,
            data_final=data_final
        )
        return jsonify({
            'success': True,
            'queued': False,
            'result': result
        })

    except Exception as e:
        logger.error(f"Erro ao importar pedidos: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _sincronizar_canais_da_regra(regra_id, modalidade_ids, modalidade_principal=None):
    """Define quais canais saem nesta janela.

    Canais diferentes podem seguir a mesma regra e sair no mesmo caminhao
    (Shopee Xpress e Retirada pelo Comprador). Sem isso, compartilhar janela so
    era possivel classificando um canal como o outro — foi o que aconteceu com o
    canal 90024 e o que a torre passou a mostrar como um lote so.

    A modalidade principal nunca sai da lista: ela e quem da o rotulo e o codigo
    da demanda, e remove-la deixaria a janela sem dono.
    """
    if modalidade_ids is None:
        return
    desejados = {int(m) for m in modalidade_ids if m is not None}
    if modalidade_principal is not None:
        desejados.add(int(modalidade_principal))
    if not desejados:
        return

    atuais = {
        row['modalidade_id']
        for row in (supabase_db.table('regra_logistica_modalidades')
                    .select('modalidade_id').eq('regra_id', regra_id).execute().data or [])
    }

    novos = desejados - atuais
    if novos:
        supabase_db.table('regra_logistica_modalidades').upsert(
            [{'regra_id': regra_id, 'modalidade_id': m} for m in sorted(novos)],
            on_conflict='regra_id,modalidade_id'
        ).execute()

    removidos = atuais - desejados
    for m in removidos:
        supabase_db.table('regra_logistica_modalidades') \
            .delete().eq('regra_id', regra_id).eq('modalidade_id', m).execute()


@integracao_canais_bp.route('/logistica/regras', methods=['GET'])
@login_required
def listar_regras_logisticas_integracao():
    """Lista regras logísticas por integração instalada."""
    try:
        marketplace_integration_id = request.args.get('marketplace_integration_id')
        # Existem DOIS caminhos entre regra e modalidade desde que uma janela
        # passou a poder servir varios canais: a FK da modalidade principal e a
        # tabela de membresia. O PostgREST recusa o embed ambiguo, entao cada
        # lado e nomeado:
        #   modalidades_logisticas -> a principal, que da o rotulo e o codigo
        #   canais                 -> todos os canais que saem neste lote
        query = supabase_db.table('regras_logisticas_integracao').select(
            "*, pontos_coleta(nome, horario_fechamento),"
            " installed_integrations(id, instance_name, module_id),"
            " modalidades_logisticas:modalidades_logisticas"
            "!regras_logisticas_integracao_modalidade_id_fkey"
            "(id, codigo, nome, cor, tipo_prazo, entra_na_torre),"
            " canais:modalidades_logisticas!regra_logistica_modalidades"
            "(id, codigo, nome, cor, ordem_exibicao, entrega_rapida)"
        ).order('marketplace_integration_id').order('prioridade_uso')
        if marketplace_integration_id:
            query = query.eq('marketplace_integration_id', int(marketplace_integration_id))
        result = query.execute()
        return jsonify({'success': True, 'data': result.data or []})
    except Exception as e:
        logger.error(f"Erro ao listar regras logísticas por integração: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/regras', methods=['POST'])
@login_required
def criar_regra_logistica_integracao():
    """Cria regra logística por integração."""
    try:
        data = request.get_json() or {}
        # `modalidade_id` e a fonte de verdade; a coluna `modalidade` (texto) e
        # projetada por trigger no banco. Aceitar apenas o id impede que a tela
        # reintroduza o vocabulario paralelo que a unificacao acabou de fechar.
        for field in ('marketplace_integration_id', 'modalidade_id', 'tipo_envio'):
            if data.get(field) in (None, ''):
                return jsonify({'success': False, 'error': f'Campo obrigatório: {field}'}), 400

        dias_semana = data.get('dias_semana') or [1, 2, 3, 4, 5]
        if any(int(d) < 1 or int(d) > 7 for d in dias_semana):
            return jsonify({'success': False, 'error': 'dias_semana deve usar 1=segunda ... 7=domingo'}), 400

        # A forma da janela segue o tipo de prazo da modalidade: hora de parede
        # para FIXO, minutos após a venda para RELATIVO. O banco valida de novo
        # no trigger — aqui é só para a mensagem chegar legível na tela.
        modalidade = supabase_db.table('modalidades_logisticas').select(
            'id, codigo, tipo_prazo'
        ).eq('id', int(data['modalidade_id'])).limit(1).execute()
        tipo_prazo = ((modalidade.data or [{}])[0]).get('tipo_prazo') or 'FIXO'

        payload = {
            'marketplace_integration_id': int(data['marketplace_integration_id']),
            'modalidade_id': int(data['modalidade_id']),
            # Placeholder: o trigger tg_regra_logistica_sync_modalidade
            # sobrescreve com o codigo real da modalidade.
            'modalidade': 'STANDARD',
            'tipo_envio': str(data['tipo_envio']).upper(),
            'ponto_coleta_id': data.get('ponto_coleta_id'),
            'dias_semana': [int(d) for d in dias_semana],
            'ativo': bool(data.get('ativo', True)),
            'prioridade_uso': int(data.get('prioridade_uso', 100)),
            'descricao': data.get('descricao'),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
        }

        if tipo_prazo == 'RELATIVO':
            for field in ('offset_etiqueta_min', 'offset_coleta_min'):
                if data.get(field) in (None, ''):
                    return jsonify({'success': False, 'error': f'Modalidade de prazo relativo: {field} é obrigatório'}), 400
            etiqueta = int(data['offset_etiqueta_min'])
            coleta = int(data['offset_coleta_min'])
            if etiqueta <= 0 or coleta <= 0:
                return jsonify({'success': False, 'error': 'Os prazos em minutos devem ser maiores que zero'}), 400
            if coleta < etiqueta:
                return jsonify({'success': False, 'error': 'A coleta não pode vir antes da etiqueta'}), 400
            payload['offset_etiqueta_min'] = etiqueta
            payload['offset_coleta_min'] = coleta
        else:
            if data.get('horario_corte') in (None, ''):
                return jsonify({'success': False, 'error': 'Informe a hora de corte: e ela que decide quais pedidos entram neste lote'}), 400
            # Ponto de coleta nao tem hora propria no caso normal: a hora e o
            # fechamento do ponto, cadastrado uma vez em pontos_coleta.
            e_ponto = payload.get('tipo_envio') == 'PONTO_COLETA'
            coleta = data.get('horario_coleta') or None
            if not coleta and not e_ponto:
                return jsonify({'success': False, 'error': 'Campo obrigatório: horario_coleta'}), 400
            if coleta and str(coleta) < str(data['horario_corte']):
                return jsonify({'success': False, 'error': 'A hora de saída deve ser maior ou igual à hora de corte'}), 400
            payload['horario_corte'] = data['horario_corte']
            payload['horario_coleta'] = coleta
            payload['horario_limite'] = data.get('horario_limite') or coleta

        result = supabase_db.table('regras_logisticas_integracao').insert(payload).execute()
        criada = (result.data or [None])[0]
        if criada:
            _sincronizar_canais_da_regra(criada['id'], data.get('modalidade_ids'), criada.get('modalidade_id'))
        return jsonify({'success': True, 'data': criada}), 201
    except Exception as e:
        logger.error(f"Erro ao criar regra logística por integração: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/regras/<int:regra_id>', methods=['PUT'])
@login_required
def atualizar_regra_logistica_integracao(regra_id: int):
    """Atualiza regra logística por integração."""
    try:
        data = request.get_json() or {}
        # `modalidade` fora da lista de propósito: e coluna projetada.
        allowed = {
            'modalidade_id', 'tipo_envio', 'horario_corte', 'horario_coleta', 'horario_limite', 'ponto_coleta_id',
            'dias_semana', 'ativo', 'prioridade_uso', 'descricao',
            'offset_etiqueta_min', 'offset_coleta_min'
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if 'modalidade_id' in updates:
            updates['modalidade_id'] = int(updates['modalidade_id'])
        if 'tipo_envio' in updates:
            updates['tipo_envio'] = str(updates['tipo_envio']).upper()
        if 'dias_semana' in updates:
            if any(int(d) < 1 or int(d) > 7 for d in updates['dias_semana']):
                return jsonify({'success': False, 'error': 'dias_semana deve usar 1=segunda ... 7=domingo'}), 400
            updates['dias_semana'] = [int(d) for d in updates['dias_semana']]
        if updates.get('horario_coleta') and updates.get('horario_corte') and str(updates['horario_coleta']) < str(updates['horario_corte']):
            return jsonify({'success': False, 'error': 'horario_coleta deve ser maior ou igual a horario_corte'}), 400
        if 'horario_coleta' in updates and 'horario_limite' not in updates:
            updates['horario_limite'] = updates['horario_coleta']
        updates['updated_at'] = datetime.utcnow().isoformat()

        # Hora de saida em branco numa janela de ponto de coleta e o caso NORMAL:
        # a hora vem do fechamento do ponto. So nao pode ficar em branco quando a
        # saida e coleta local, que nao tem de onde herdar.
        if updates.get('horario_coleta') in (None, ''):
            updates['horario_coleta'] = None
            updates['horario_limite'] = None

        result = supabase_db.table('regras_logisticas_integracao').update(updates).eq('id', regra_id).execute()
        atualizada = (result.data or [None])[0]
        if atualizada:
            _sincronizar_canais_da_regra(regra_id, data.get('modalidade_ids'), atualizada.get('modalidade_id'))
        return jsonify({'success': True, 'data': atualizada})
    except Exception as e:
        logger.error(f"Erro ao atualizar regra logística por integração {regra_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/regras/<int:regra_id>', methods=['DELETE'])
@login_required
def remover_regra_logistica_integracao(regra_id: int):
    """Remove regra logística por integração."""
    try:
        supabase_db.table('regras_logisticas_integracao').delete().eq('id', regra_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Erro ao remover regra logística por integração {regra_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/modalidades', methods=['GET'])
@login_required
def listar_modalidades_logisticas():
    """Modalidades cadastradas, opcionalmente filtradas pelo modulo da integração."""
    try:
        module_id = request.args.get('module_id')
        marketplace_integration_id = request.args.get('marketplace_integration_id')

        if not module_id and marketplace_integration_id:
            ii = supabase_db.table('installed_integrations').select('module_id').eq(
                'id', int(marketplace_integration_id)
            ).limit(1).execute()
            module_id = ((ii.data or [{}])[0]).get('module_id')

        query = supabase_db.table('modalidades_logisticas').select('*').eq('ativo', True).order('ordem_exibicao')
        if module_id:
            query = query.eq('module_id', module_id)
        result = query.execute()
        return jsonify({'success': True, 'data': result.data or []})
    except Exception as e:
        logger.error(f"Erro ao listar modalidades logísticas: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/canais', methods=['GET'])
@login_required
def listar_canais_envio_observados():
    """Canais de envio vistos no tráfego real, com a modalidade associada.

    Não é catálogo cadastrado: é o distinct do que a origem de fato mandou,
    alimentado pelo ingest. Canal novo aparece aqui sozinho, sem deploy.
    """
    try:
        marketplace_integration_id = request.args.get('marketplace_integration_id')
        result = supabase_db.rpc('canais_envio_observados', {
            'p_integration_id': int(marketplace_integration_id) if marketplace_integration_id else None
        }).execute()
        return jsonify({'success': True, 'data': result.data or []})
    except Exception as e:
        logger.error(f"Erro ao listar canais de envio observados: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/canais/associar', methods=['POST'])
@login_required
def associar_canal_modalidade():
    """Associa um canal de envio a uma modalidade e reclassifica os pendentes.

    `modalidade_id` nulo desassocia: a regra e desativada (não apagada, para o
    histórico continuar auditável) e os pedidos pendentes voltam para
    "Modalidade não classificada".
    """
    try:
        data = request.get_json() or {}
        module_id = data.get('module_id')
        chave = data.get('chave')
        if not module_id or not chave:
            return jsonify({'success': False, 'error': 'module_id e chave são obrigatórios'}), 400

        modalidade_id = data.get('modalidade_id')
        result = supabase_db.rpc('associar_canal_modalidade', {
            'p_module_id': str(module_id),
            'p_chave': str(chave),
            'p_modalidade_id': int(modalidade_id) if modalidade_id not in (None, '', 'none') else None,
            'p_campo_origem': data.get('campo_origem'),
        }).execute()

        row = (result.data or [{}])[0] if isinstance(result.data, list) else (result.data or {})
        return jsonify({
            'success': True,
            'data': {
                'regra_id': row.get('out_regra_id'),
                'pedidos_reclassificados': row.get('out_pedidos_reclassificados', 0),
            }
        })
    except Exception as e:
        logger.error(f"Erro ao associar canal de envio à modalidade: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
