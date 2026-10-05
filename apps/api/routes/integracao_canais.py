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

from flask import request, Blueprint, jsonify, session
from werkzeug.exceptions import HTTPException
from routes.auth import login_required, admin_required
from nistiprint_shared.services import logistica_manutencao_service as logistica
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
@admin_required
def criar_regra_logistica_integracao():
    return _logistica_response(lambda: logistica.salvar_regra(request.get_json(), ator=str(session['user_id'])), 201)


@integracao_canais_bp.route('/logistica/regras/<int:regra_id>', methods=['PUT'])
@admin_required
def atualizar_regra_logistica_integracao(regra_id):
    return _logistica_response(lambda: logistica.salvar_regra(request.get_json(), regra_id, str(session['user_id'])))


@integracao_canais_bp.route('/logistica/regras/<int:regra_id>', methods=['DELETE'])
@admin_required
def remover_regra_logistica_integracao(regra_id: int):
    """Remove regra logística por integração."""
    try:
        logistica.salvar_regra({'ativo': False}, regra_id, str(session['user_id']))
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

        query = supabase_db.table('modalidades_logisticas').select('*').order('ordem_exibicao')
        if request.args.get('incluir_inativas') != 'true':
            query = query.eq('ativo', True)
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
        result = logistica.rpc_data('logistica_identificadores_observados', {
            'p_integration_id': int(marketplace_integration_id) if marketplace_integration_id else None
        })
        return jsonify({'success': True, 'data': result or []})
    except Exception as e:
        logger.error(f"Erro ao listar canais de envio observados: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@integracao_canais_bp.route('/logistica/canais/associar', methods=['POST'])
@admin_required
def associar_canal_modalidade():
    return _logistica_response(lambda: logistica.associar(request.get_json(), str(session['user_id'])))


def _logistica_response(call, status=200):
    try:
        return jsonify({'success': True, 'data': call()}), status
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except HTTPException as exc:
        return jsonify({'success': False, 'error': 'Informe um JSON valido'}), exc.code
    except Exception as exc:
        code = str(getattr(exc, 'code', ''))
        if code in {'22023', '23514', '23503', '23502', '22P02', '22007', '23505', 'P0002'}:
            return jsonify({'success': False, 'error': getattr(exc, 'message', str(exc))}), (409 if code == '23505' else 404 if code == 'P0002' else 400)
        logger.exception('Falha na manutencao logistica')
        return jsonify({'success': False, 'error': 'Falha ao processar logistica'}), 500


@integracao_canais_bp.route('/logistica/modalidades', methods=['POST'])
@admin_required
def criar_modalidade_logistica():
    return _logistica_response(lambda: logistica.salvar_modalidade(request.get_json(), ator=str(session['user_id'])), 201)


@integracao_canais_bp.route('/logistica/modalidades/<int:modalidade_id>', methods=['PUT'])
@admin_required
def atualizar_modalidade_logistica(modalidade_id):
    return _logistica_response(lambda: logistica.salvar_modalidade(request.get_json(), modalidade_id, str(session['user_id'])))


@integracao_canais_bp.route('/logistica/associacoes', methods=['GET'])
@login_required
def listar_associacoes_logisticas():
    def carregar():
        query = supabase_db.table('regras_classificacao_modalidade').select('*,modalidades_logisticas(nome)') \
            .eq('alvo', 'CHAVE').is_('integration_id', None).order('id')
        if request.args.get('module_id'):
            query = query.eq('module_id', request.args['module_id'])
        return query.execute().data or []
    return _logistica_response(carregar)


@integracao_canais_bp.route('/logistica/agenda', methods=['GET'])
@login_required
def consultar_agenda_logistica():
    def carregar():
        inicio, fim = logistica.validar_periodo(request.args['inicio'], request.args['fim'])
        return logistica.rpc_data('logistica_agenda_periodo', {'p_integration_id': int(request.args['marketplace_integration_id']),
            'p_inicio': inicio, 'p_fim': fim})
    if not all(request.args.get(k) for k in ('inicio', 'fim', 'marketplace_integration_id')):
        return jsonify({'success': False, 'error': 'Informe integracao, inicio e fim'}), 400
    return _logistica_response(carregar)


@integracao_canais_bp.route('/logistica/sincronizar', methods=['POST'])
@admin_required
def sincronizar_agenda_logistica():
    def enfileirar():
        from nistiprint_shared.services.celery_app import celery_app
        body = request.get_json() or {}
        iid = int(body['marketplace_integration_id'])
        rows = supabase_db.table('installed_integrations').select('id,module_id').eq('id', iid).execute().data or []
        if not rows or rows[0]['module_id'] != 'mercadolivre':
            raise ValueError('Selecione uma conta Mercado Livre')
        task = celery_app.send_task('nistiprint_shared.services.logistica_sync_service.sincronizar_agendas', args=[iid])
        return {'operation_id': task.id, 'status': 'ENFILEIRADO'}
    if not (request.get_json(silent=True) or {}).get('marketplace_integration_id'):
        return jsonify({'success': False, 'error': 'Informe a integracao'}), 400
    return _logistica_response(enfileirar, 202)


@integracao_canais_bp.route('/logistica/regras/<int:regra_id>/excecoes/<dia>', methods=['PUT', 'DELETE'])
@admin_required
def salvar_excecao_logistica(regra_id, dia):
    def salvar():
        from datetime import date
        date.fromisoformat(dia)
        dados = request.get_json(silent=True) if request.method == 'PUT' else None
        if request.method == 'PUT' and not isinstance(dados, dict):
            raise ValueError('Informe janelas e motivo em JSON')
        return logistica.rpc_data('logistica_salvar_excecao', {'p_regra_id': regra_id, 'p_dia': dia,
            'p_dados': dados, 'p_ator': str(session['user_id'])})
    return _logistica_response(salvar)
