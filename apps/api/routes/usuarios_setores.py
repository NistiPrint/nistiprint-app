from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from nistiprint_shared.services.setor_service import setor_service
from nistiprint_shared.services.usuario_service import usuario_service
from nistiprint_shared.services.permissao_service import permissao_service
from nistiprint_shared.models.permissao import Recurso
from routes.auth import admin_required, get_current_user
from nistiprint_shared.database.supabase_db_service import get_current_database_mode, DatabaseMode
from nistiprint_shared.services.auditoria_service import auditoria_service


def _audit(event_type, description, entity_id=None, actor=None, entity_type=None, before=None, after=None):
    try:
        payload = {
            'entidade_tipo': entity_type or ('usuario' if entity_id else 'setor'),
            'entidade_id': entity_id,
            'descricao': description,
        }
        if before is not None:
            payload['dados_anteriores'] = before
        if after is not None:
            payload['dados_novos'] = after
        auditoria_service.log_event(event_type, payload, user_id=(actor or {}).get('id'))
    except Exception:
        # A failed audit write should be observable without returning a false
        # failure after the account change has already committed.
        import logging
        logging.getLogger(__name__).exception('Não foi possível registrar evento de acesso.')


def _create_auth_user(email, password, name):
    if get_current_database_mode() != DatabaseMode.SUPABASE:
        return None
    from nistiprint_shared.services.supabase_auth_service import supabase_auth
    return supabase_auth.create_user(email, password, name)

usuarios_setores_bp = Blueprint('usuarios_setores', __name__)
usuarios_setores_api_bp = Blueprint('usuarios_setores_api', __name__, url_prefix='/api/v2/usuarios-setores')

# Legacy routes to prevent BuildError in templates
@usuarios_setores_bp.route('/usuarios')
@admin_required
def usuario_list():
    return render_template('usuarios/list.html')

@usuarios_setores_bp.route('/setores')
@admin_required
def setor_list():
    return render_template('setores/list.html')

# API Setor routes
@usuarios_setores_api_bp.route('/setor', methods=['GET'])
@admin_required
def api_setor_list():
    try:
        setores = (setor_service.get_all() if request.args.get('ativos') == 'true'
                   else setor_service.get_all_including_inactive())
        return jsonify({'setores': setores})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/setor', methods=['POST'])
@admin_required
def api_setor_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        setor_data = {
            'nome': data.get('nome'),
            'descricao': data.get('descricao', ''),
            'ativo': data.get('ativo', True)
        }
        new_setor = setor_service.create(setor_data)
        _audit('SETOR_CRIADO', 'Setor criado ou reativado.', new_setor.get('id'), get_current_user(), 'setor',
               after={key: new_setor.get(key) for key in ('nome', 'descricao', 'ativo')})
        return jsonify({'success': True, 'message': 'Setor criado com sucesso!', 'setor': new_setor}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/setor/<setor_id>', methods=['GET'])
@admin_required
def api_setor_get(setor_id):
    try:
        setor = setor_service.get_by_id_including_inactive(int(setor_id))
        if not setor:
            return jsonify({'error': 'Setor não encontrado.'}), 404
        return jsonify({'setor': setor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/setor/<setor_id>', methods=['PUT'])
@admin_required
def api_setor_edit(setor_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        setor_data = {
            'nome': data.get('nome'),
            'descricao': data.get('descricao', ''),
            'ativo': data.get('ativo', True)
        }
        current = setor_service.get_by_id_including_inactive(int(setor_id))
        if not current:
            return jsonify({'error': 'Setor não encontrado.'}), 404
        updated_setor = setor_service.update(int(setor_id), setor_data)
        safe_fields = ('nome', 'descricao', 'ativo')
        _audit('SETOR_ATUALIZADO', 'Dados ou status do setor atualizados.', int(setor_id), get_current_user(), 'setor',
               before={key: current.get(key) for key in safe_fields},
               after={key: updated_setor.get(key) for key in safe_fields})
        return jsonify({'success': True, 'message': 'Setor atualizado com sucesso!', 'setor': updated_setor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/setor/<setor_id>', methods=['DELETE'])
@admin_required
def api_setor_delete(setor_id):
    try:
        current = setor_service.get_by_id_including_inactive(int(setor_id))
        if not current:
            return jsonify({'error': 'Setor não encontrado.'}), 404
        setor_service.delete(int(setor_id))
        _audit('SETOR_DESATIVADO', 'Setor desativado.', int(setor_id), get_current_user(), 'setor',
               before={'ativo': current.get('ativo')}, after={'ativo': False})
        return jsonify({'success': True, 'message': 'Setor deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Permission Routes
@usuarios_setores_api_bp.route('/recursos', methods=['GET'])
@admin_required
def api_recursos_list():
    try:
        recursos = Recurso.query.all()
        return jsonify({'recursos': [r.to_dict() for r in recursos]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/setor/<setor_id>/permissoes', methods=['GET'])
@admin_required
def api_setor_permissoes_get(setor_id):
    try:
        permissoes = permissao_service.get_setor_permissions(int(setor_id))
        return jsonify({'permissoes': permissoes})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/setor/<setor_id>/permissoes', methods=['POST'])
@admin_required
def api_setor_permissoes_update(setor_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
            
        recurso_nome = data.get('recurso')
        pode_ler = data.get('ler')
        pode_criar = data.get('criar')
        pode_editar = data.get('editar')
        pode_excluir = data.get('excluir')
        
        before_all = permissao_service.get_setor_permissions(int(setor_id))
        before = before_all.get(recurso_nome, {})
        permissao = permissao_service.update_setor_permission(
            setor_id=int(setor_id),
            recurso_nome=recurso_nome,
            pode_ler=pode_ler,
            pode_criar=pode_criar,
            pode_editar=pode_editar,
            pode_excluir=pode_excluir
        )
        _audit('PERMISSAO_SETOR_ATUALIZADA', 'Permissão de recurso atualizada.', int(setor_id), get_current_user(), 'setor',
               before=before, after={key: permissao.get(key) for key in ('pode_ler', 'pode_criar', 'pode_editar', 'pode_excluir')})
        return jsonify({'success': True, 'permissao': permissao})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@usuarios_setores_api_bp.route('/setor/<setor_id>/permissoes-demanda', methods=['GET', 'PUT'])
@admin_required
def api_setor_permissoes_demanda(setor_id):
    try:
        sector_id = int(setor_id)
        if request.method == 'GET':
            return jsonify({'permissoes': permissao_service.get_demand_permissions(sector_id)})
        data = request.get_json(silent=True) or {}
        before = permissao_service.get_demand_permissions(sector_id)
        permissions = permissao_service.update_demand_permissions(
            sector_id, data.get('fields'), data.get('actions'),
        )
        _audit('PERMISSAO_DEMANDA_ATUALIZADA', 'Permissões de demanda do setor atualizadas.', sector_id, get_current_user(), 'setor',
               before=before, after=permissions)
        return jsonify({'success': True, 'permissoes': permissions})
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível salvar as permissões do setor.'}), 500

# API Usuario routes
@usuarios_setores_api_bp.route('/usuario', methods=['GET'])
@admin_required
def api_usuario_list():
    try:
        usuarios = usuario_service.get_all()
        return jsonify({'usuarios': usuarios})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/usuario', methods=['POST'])
@admin_required
def api_usuario_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        nome = str(data.get('nome') or '').strip()
        email = str(data.get('email') or '').strip().lower()
        senha = data.get('senha')
        if not nome or not email or not isinstance(senha, str) or len(senha) < 8:
            return jsonify({'error': 'Nome, e-mail e senha inicial com ao menos 8 caracteres são obrigatórios.'}), 400

        usuario_data = {
            'nome': nome,
            'email': email,
            'senha': senha,
            'setor_id': int(data.get('setor_id')),
            'ativo': data.get('ativo', True),
            'is_admin': data.get('is_admin', False),
            'must_change_password': True,
        }
        new_usuario = usuario_service.create(usuario_data)
        auth_user = None
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            try:
                auth_user = _create_auth_user(email, senha, nome)
                new_usuario = usuario_service.update(new_usuario['id'], {'auth_user_id': str(auth_user.id)})
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Provisionamento parcial; usuário %s permanece com acesso pendente.', new_usuario.get('id'))
                _audit('USUARIO_CRIADO', 'Conta criada com acesso pendente de regularização.', new_usuario.get('id'), get_current_user(),
                       after={key: new_usuario.get(key) for key in ('nome', 'email', 'setor_id', 'ativo', 'is_admin')})
                return jsonify({
                    'success': True,
                    'access_pendente': True,
                    'message': 'Usuário criado. O acesso ao Supabase ficou pendente e pode ser regularizado no painel.',
                    'usuario': new_usuario,
                }), 202
        _audit('USUARIO_CRIADO', 'Conta de usuário criada.', new_usuario.get('id'), get_current_user(),
               after={key: new_usuario.get(key) for key in ('nome', 'email', 'setor_id', 'ativo', 'is_admin')})
        return jsonify({'success': True, 'message': 'Usuário criado com sucesso!', 'usuario': new_usuario}), 201
    except Exception as e:
        if 'auth_user' in locals() and auth_user and 'new_usuario' in locals() and not new_usuario.get('auth_user_id'):
            try:
                from nistiprint_shared.services.supabase_auth_service import supabase_auth
                supabase_auth.delete_user(str(auth_user.id))
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Falha ao reverter conta Auth não vinculada.')
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['GET'])
@admin_required
def api_usuario_get(usuario_id):
    try:
        usuario = usuario_service.get_by_id_including_inactive(int(usuario_id))
        setores = setor_service.get_all()
        if not usuario:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        return jsonify({'usuario': usuario, 'setores': setores})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['PUT'])
@admin_required
def api_usuario_edit(usuario_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        if data.get('senha'):
            return jsonify({'error': 'Use a ação de regularizar acesso para definir ou redefinir a senha.'}), 400

        usuario_data = {
            'nome': data.get('nome'),
            'email': data.get('email'),
            'setor_id': int(data.get('setor_id')) if data.get('setor_id') else None,
            'ativo': data.get('ativo', True),
            'is_admin': data.get('is_admin', False)
        }

        current = usuario_service.get_by_id_including_inactive(int(usuario_id))
        if not current:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        is_default = str(current.get('email', '')).lower() == 'admin@admin.com'
        if is_default and (
            not usuario_data['ativo'] or not usuario_data['is_admin']
            or usuario_data['email'].strip().lower() != 'admin@admin.com'
        ):
            return jsonify({'error': 'A conta administrativa padrão deve permanecer ativa e administrativa.'}), 400

        identity_changed = any([
            usuario_data['email'].strip().lower() != str(current.get('email') or '').lower(),
            bool(usuario_data['is_admin']) != bool(current.get('is_admin')),
            int(usuario_data['setor_id'] or 0) != int(current.get('setor_id') or 0),
            bool(usuario_data['ativo']) != bool(current.get('ativo')),
        ])
        auth_email_changed = False
        if usuario_data['email'].strip().lower() != str(current.get('email') or '').lower():
            if not current.get('auth_user_id') and get_current_database_mode() == DatabaseMode.SUPABASE:
                return jsonify({'error': 'Regularize o acesso do usuário antes de trocar o e-mail.'}), 409
            if current.get('auth_user_id') and get_current_database_mode() == DatabaseMode.SUPABASE:
                from nistiprint_shared.services.supabase_auth_service import supabase_auth
                supabase_auth.update_user(str(current['auth_user_id']), {
                    'email': usuario_data['email'].strip().lower(),
                    'email_confirm': True,
                })
                auth_email_changed = True
        if identity_changed:
            usuario_data['session_version'] = int(current.get('session_version') or 0) + 1

        try:
            updated_usuario = usuario_service.update(int(usuario_id), usuario_data)
        except Exception:
            if auth_email_changed:
                try:
                    supabase_auth.update_user(str(current['auth_user_id']), {
                        'email': current['email'], 'email_confirm': True,
                    })
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Falha ao reverter e-mail Auth após erro no vínculo local.')
            raise
        safe_fields = ('nome', 'email', 'setor_id', 'ativo', 'is_admin')
        _audit('USUARIO_ATUALIZADO', 'Dados, acesso ou setor do usuário atualizados.', int(usuario_id), get_current_user(),
               before={key: current.get(key) for key in safe_fields},
               after={key: updated_usuario.get(key) for key in safe_fields})
        return jsonify({'success': True, 'message': 'Usuário atualizado com sucesso!', 'usuario': updated_usuario})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['DELETE'])
@admin_required
def api_usuario_delete(usuario_id):
    try:
        current = usuario_service.get_by_id_including_inactive(int(usuario_id))
        if not current:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        usuario_service.delete(int(usuario_id))
        _audit('USUARIO_DESATIVADO', 'Conta de usuário desativada.', int(usuario_id), get_current_user(),
               before={'ativo': current.get('ativo')}, after={'ativo': False})
        return jsonify({'success': True, 'message': 'Usuário deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@usuarios_setores_api_bp.route('/usuario/<int:usuario_id>/access', methods=['POST'])
@admin_required
def api_usuario_regularizar_acesso(usuario_id):
    try:
        current = usuario_service.get_by_id_including_inactive(usuario_id)
        if not current:
            return jsonify({'success': False, 'error': 'Usuário não encontrado.'}), 404
        if not current.get('ativo'):
            return jsonify({'success': False, 'error': 'Ative a conta antes de regularizar o acesso.'}), 400
        if str(current.get('email') or '').lower() == 'admin@admin.com':
            return jsonify({'success': False, 'error': 'A senha da conta administrativa padrão não pode ser redefinida neste painel.'}), 400
        email_owner = usuario_service.get_by_email(current.get('email'))
        if not email_owner or int(email_owner.get('id')) != usuario_id:
            return jsonify({'success': False, 'error': 'O e-mail não identifica uma única conta operacional ativa.'}), 409
        password = (request.get_json(silent=True) or {}).get('senha_inicial')
        if not isinstance(password, str) or len(password) < 8:
            return jsonify({'success': False, 'error': 'A senha inicial deve ter ao menos 8 caracteres.'}), 400
        identity = current.get('auth_user_id')
        next_version = int(current.get('session_version') or 0) + 1
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            from nistiprint_shared.services.supabase_auth_service import supabase_auth
            if identity:
                # Record the forced change and revoke old app sessions before
                # changing credentials. If Auth fails, the linked account
                # remains in an explicit recovery state.
                updated = usuario_service.update(usuario_id, {
                    'must_change_password': True,
                    'session_version': next_version,
                })
                supabase_auth.update_user(str(identity), {'password': password})
            else:
                # If provisioning created the Auth identity but the local link
                # failed, resume that identity instead of failing on duplicate
                # email or presenting the pending account as ready.
                auth_user = supabase_auth.find_user_by_email(current['email'])
                if auth_user:
                    identity = str(auth_user.id)
                    supabase_auth.update_user(identity, {
                        'password': password,
                        'email_confirm': True,
                        'user_metadata': {'name': current['nome']},
                    })
                else:
                    auth_user = supabase_auth.create_user(current['email'], password, current['nome'])
                    identity = str(auth_user.id)
                try:
                    updated = usuario_service.update(usuario_id, {
                        'auth_user_id': identity,
                        'must_change_password': True,
                        'session_version': next_version,
                    })
                except Exception:
                    try:
                        supabase_auth.delete_user(identity)
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception('Falha ao limpar conta Auth provisionada parcialmente.')
                    raise
        else:
            updated = usuario_service.update(usuario_id, {
                'senha': password,
                'must_change_password': True,
                'session_version': next_version,
            })
        _audit('USUARIO_ACESSO_REGULARIZADO', 'Acesso autenticado regularizado com senha inicial.', usuario_id, get_current_user(),
               before={'auth_user_id': bool(current.get('auth_user_id')), 'must_change_password': current.get('must_change_password')},
               after={'auth_user_id': bool(identity), 'must_change_password': True})
        return jsonify({'success': True, 'usuario': updated})
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Falha ao regularizar acesso do usuário %s.', usuario_id)
        return jsonify({'success': False, 'error': 'Não foi possível regularizar o acesso.'}), 400





