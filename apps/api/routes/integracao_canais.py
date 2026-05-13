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
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

logger = logging.getLogger("IntegracaoCanaisAPI")

integracao_canais_bp = Blueprint('integracao_canais', __name__, url_prefix='/api/v2/integracao-canais')


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
        
        config = integracao_canal_service.criar_vinculo(
            canal_venda_id=data['canal_venda_id'],
            bling_loja_id=data['bling_loja_id'],
            plataforma_nome=data['plataforma_nome'],
            integration_id=data.get('integration_id'),
            bling_integration_id=data.get('bling_integration_id'),
            marketplace_integration_id=data.get('marketplace_integration_id'),
            is_primary=data.get('is_primary', False),
            process_webhooks=data.get('process_webhooks', True),
            config_json=data.get('config_json', {})
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
                         'is_primary', 'is_active', 'process_webhooks', 'config_json']
        updates = {k: v for k, v in data.items() if k in allowed_fields}
        
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
