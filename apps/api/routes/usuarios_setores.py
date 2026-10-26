import re
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


def _set_and_verify_auth_password(auth_service, auth_user_id, email, password, extra_attributes=None):
    attributes = dict(extra_attributes or {})
    attributes['password'] = password
    updated_user = auth_service.update_user(str(auth_user_id), attributes)
    if updated_user and str(getattr(updated_user, 'id', '')) != str(auth_user_id):
        raise RuntimeError('O Supabase atualizou uma identidade diferente da conta selecionada.')
    authenticated_user = auth_service.authenticate(email, password)
    if not authenticated_user or str(authenticated_user.get('id')) != str(auth_user_id):
        raise RuntimeError('O Supabase não validou a senha temporária para a identidade selecionada.')
    return updated_user


def _with_access_status(usuario):
    usuario = dict(usuario)
    if get_current_database_mode() == DatabaseMode.SUPABASE and not usuario.get('auth_user_id'):
        usuario['access_status'] = 'pending'
    elif usuario.get('must_change_password'):
        usuario['access_status'] = 'password_change_required'
    else:
        usuario['access_status'] = 'ready'
    return usuario


def _validated_user_data(data, *, creating=False):
    if not isinstance(data, dict):
        raise ValueError('Dados inválidos.')
    nome = str(data.get('nome') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    if not nome or len(nome) > 100:
        raise ValueError('Informe um nome com até 100 caracteres.')
    if len(email) > 120 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise ValueError('Informe um e-mail válido com até 120 caracteres.')
    try:
        setor_id = int(data.get('setor_id'))
    except (TypeError, ValueError):
        raise ValueError('Selecione um setor válido.')
    if setor_id <= 0:
        raise ValueError('Selecione um setor válido.')
    for field in ('ativo', 'is_admin'):
        if field in data and not isinstance(data[field], bool):
            raise ValueError(f'O campo {field} deve ser verdadeiro ou falso.')
    result = {
        'nome': nome,
        'email': email,
        'setor_id': setor_id,
        'ativo': data.get('ativo', True),
        'is_admin': data.get('is_admin', False),
    }
    if creating:
        password = data.get('senha')
        if not isinstance(password, str) or len(password) < 8:
            raise ValueError('A senha inicial deve ter ao menos 8 caracteres.')
        result['senha'] = password
        result['must_change_password'] = True
    elif data.get('senha'):
        raise ValueError('Use a ação de redefinir senha para alterar a senha.')
    return result

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
        return jsonify({'usuarios': [_with_access_status(usuario) for usuario in usuarios]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/usuario', methods=['POST'])
@admin_required
def api_usuario_new():
    auth_user = None
    auth_identity_created_here = False
    recovered_auth_identity = False
    try:
        data = request.get_json(silent=True)
        usuario_data = _validated_user_data(data, creating=True)
        nome = usuario_data['nome']
        email = usuario_data['email']
        senha = usuario_data['senha']
        usuario_service.validate_create(usuario_data)
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            from nistiprint_shared.services.supabase_auth_service import supabase_auth
            try:
                existing_auth_user = supabase_auth.find_user_by_email(email)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Não foi possível verificar duplicidade no Supabase Auth.')
                return jsonify({
                    'success': False,
                    'error': 'Não foi possível verificar o e-mail no Supabase Auth. O cadastro não foi criado; tente novamente.',
                }), 503
            if existing_auth_user:
                # Recover an Auth-only account left by an interrupted earlier
                # create attempt. A local duplicate was rejected by
                # validate_create above, so this identity has no operational
                # user row to conflict with.
                try:
                    _set_and_verify_auth_password(supabase_auth, existing_auth_user.id, email, senha, {
                        'email_confirm': True,
                        'user_metadata': {'name': nome},
                    })
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Não foi possível preparar identidade Auth existente para recuperação.')
                    return jsonify({
                        'success': False,
                        'error': 'A identidade já existe no Supabase Auth, mas não foi possível atualizar a senha temporária. Tente novamente.',
                    }), 502
                auth_user = existing_auth_user
                recovered_auth_identity = True

        creation_data = dict(usuario_data)
        if recovered_auth_identity:
            creation_data['auth_user_id'] = str(auth_user.id)
        new_usuario = usuario_service.create(creation_data)
        if new_usuario.get('id') is None:
            raise RuntimeError('O cadastro não foi confirmado no banco de dados. Tente novamente.')
        if get_current_database_mode() == DatabaseMode.SUPABASE and not recovered_auth_identity:
            try:
                auth_user = _create_auth_user(email, senha, nome)
                auth_identity_created_here = True
                _set_and_verify_auth_password(supabase_auth, auth_user.id, email, senha)
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
                    'usuario': _with_access_status(new_usuario),
                }), 202
        description = ('Cadastro operacional recuperado e vinculado à identidade Auth existente.'
                       if recovered_auth_identity else 'Conta de usuário criada.')
        _audit('USUARIO_CRIADO', description, new_usuario.get('id'), get_current_user(),
               after={key: new_usuario.get(key) for key in ('nome', 'email', 'setor_id', 'ativo', 'is_admin')})
        message = ('Cadastro operacional recuperado. O usuário deverá trocar a senha no próximo acesso.'
                   if recovered_auth_identity else 'Usuário criado com sucesso!')
        return jsonify({'success': True, 'message': message, 'usuario': _with_access_status(new_usuario)}), 201
    except Exception as e:
        if auth_identity_created_here and auth_user and 'new_usuario' in locals() and not new_usuario.get('auth_user_id'):
            try:
                from nistiprint_shared.services.supabase_auth_service import supabase_auth
                supabase_auth.delete_user(str(auth_user.id))
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Falha ao reverter conta Auth não vinculada.')
        status = 409 if 'já existe' in str(e).lower() else 400
        return jsonify({'error': str(e)}), status

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['GET'])
@admin_required
def api_usuario_get(usuario_id):
    try:
        usuario = usuario_service.get_by_id_including_inactive(int(usuario_id))
        setores = setor_service.get_all()
        if not usuario:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        return jsonify({'usuario': _with_access_status(usuario), 'setores': setores})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['PUT'])
@admin_required
def api_usuario_edit(usuario_id):
    try:
        data = request.get_json(silent=True)
        usuario_data = _validated_user_data(data)

        current = usuario_service.get_by_id_including_inactive(int(usuario_id))
        if not current:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        if 'ativo' in data and usuario_data['ativo'] != bool(current.get('ativo')):
            return jsonify({'error': 'Use a ação de desativar ou reativar para alterar o status da conta.'}), 400
        usuario_data['ativo'] = bool(current.get('ativo'))
        if 'is_admin' not in data:
            usuario_data['is_admin'] = bool(current.get('is_admin'))
        is_default = str(current.get('email', '')).lower() == 'admin@admin.com'
        if is_default and (
            not usuario_data['ativo'] or not usuario_data['is_admin']
            or usuario_data['email'].strip().lower() != 'admin@admin.com'
        ):
            return jsonify({'error': 'A conta administrativa padrão deve permanecer ativa e administrativa.'}), 400

        # Complete local validation before changing the external Auth identity.
        usuario_service.validate_update(int(usuario_id), usuario_data)

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
        return jsonify({'success': True, 'message': 'Usuário atualizado com sucesso!', 'usuario': _with_access_status(updated_usuario)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['DELETE'])
@admin_required
def api_usuario_delete(usuario_id):
    try:
        current = usuario_service.get_by_id_including_inactive(int(usuario_id))
        if not current:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        if not current.get('ativo'):
            return jsonify({'error': 'A conta já está desativada.'}), 409
        usuario_service.delete(int(usuario_id))
        _audit('USUARIO_DESATIVADO', 'Conta de usuário desativada.', int(usuario_id), get_current_user(),
               before={'ativo': current.get('ativo')}, after={'ativo': False})
        return jsonify({'success': True, 'message': 'Usuário desativado com sucesso!'})
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
        if not usuario_service.email_belongs_uniquely_to(current.get('email'), usuario_id):
            return jsonify({'success': False, 'error': 'O e-mail não identifica uma única conta operacional.'}), 409
        password = (request.get_json(silent=True) or {}).get('senha_inicial')
        if not isinstance(password, str) or len(password) < 8:
            return jsonify({'success': False, 'error': 'A senha inicial deve ter ao menos 8 caracteres.'}), 400
        identity = current.get('auth_user_id')
        next_version = int(current.get('session_version') or 0) + 1
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            from nistiprint_shared.services.supabase_auth_service import supabase_auth
            if identity:
                # Fail closed and revoke old sessions before changing Auth.
                updated = usuario_service.update(usuario_id, {
                    'must_change_password': True,
                    'session_version': next_version,
                })
                try:
                    _set_and_verify_auth_password(supabase_auth, identity, current['email'], password)
                except Exception:
                    return jsonify({'success': False, 'error': 'Não foi possível atualizar a senha no provedor. A conta exige troca de senha; tente novamente.'}), 502
            else:
                # If provisioning created the Auth identity but the local link
                # failed, resume that identity instead of failing on duplicate
                # email or presenting the pending account as ready.
                auth_user = supabase_auth.find_user_by_email(current['email'])
                created_identity = False
                if auth_user:
                    identity = str(auth_user.id)
                    _set_and_verify_auth_password(supabase_auth, identity, current['email'], password, {
                        'email_confirm': True,
                        'user_metadata': {'name': current['nome']},
                    })
                else:
                    auth_user = supabase_auth.create_user(current['email'], password, current['nome'])
                    identity = str(auth_user.id)
                    created_identity = True
                    authenticated_user = supabase_auth.authenticate(current['email'], password)
                    if not authenticated_user or str(authenticated_user.get('id')) != identity:
                        raise RuntimeError('O Supabase não validou a senha temporária para a identidade criada.')
                try:
                    updated = usuario_service.update(usuario_id, {
                        'auth_user_id': identity,
                        'must_change_password': True,
                        'session_version': next_version,
                    })
                except Exception:
                    if created_identity:
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
        return jsonify({'success': True, 'usuario': _with_access_status(updated)})
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Falha ao regularizar acesso do usuário %s.', usuario_id)
        return jsonify({'success': False, 'error': 'Não foi possível regularizar o acesso.'}), 400


@usuarios_setores_api_bp.route('/usuario/<int:usuario_id>/reactivate', methods=['POST'])
@admin_required
def api_usuario_reactivate(usuario_id):
    try:
        current = usuario_service.get_by_id_including_inactive(usuario_id)
        if not current:
            return jsonify({'success': False, 'error': 'Usuário não encontrado.'}), 404
        if current.get('ativo'):
            return jsonify({'success': False, 'error': 'A conta já está ativa.'}), 409
        if str(current.get('email') or '').strip().lower() == 'admin@admin.com':
            return jsonify({'success': False, 'error': 'A conta administrativa padrão não pode ser reativada por este painel.'}), 400
        try:
            setor_id = int(current.get('setor_id'))
        except (TypeError, ValueError):
            setor_id = 0
        if not setor_id or not setor_service.get_by_id(setor_id):
            return jsonify({'success': False, 'error': 'Ative ou atribua um setor ativo antes de reativar a conta.'}), 409
        if not usuario_service.email_belongs_uniquely_to(current.get('email'), usuario_id):
            return jsonify({'success': False, 'error': 'O e-mail não identifica uma única conta operacional ativa.'}), 409
        password = (request.get_json(silent=True) or {}).get('senha_inicial')
        if not isinstance(password, str) or len(password) < 8:
            return jsonify({'success': False, 'error': 'A senha inicial deve ter ao menos 8 caracteres.'}), 400

        identity = current.get('auth_user_id')
        created_identity = False
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            from nistiprint_shared.services.supabase_auth_service import supabase_auth
            if identity:
                _set_and_verify_auth_password(supabase_auth, identity, current['email'], password)
            else:
                auth_user = supabase_auth.find_user_by_email(current['email'])
                if auth_user:
                    identity = str(auth_user.id)
                    _set_and_verify_auth_password(supabase_auth, identity, current['email'], password, {
                        'email_confirm': True,
                        'user_metadata': {'name': current['nome']},
                    })
                else:
                    auth_user = supabase_auth.create_user(current['email'], password, current['nome'])
                    identity = str(auth_user.id)
                    created_identity = True
                    authenticated_user = supabase_auth.authenticate(current['email'], password)
                    if not authenticated_user or str(authenticated_user.get('id')) != identity:
                        raise RuntimeError('O Supabase não validou a senha temporária para a identidade criada.')

        try:
            updated = usuario_service.update(usuario_id, {
                'ativo': True,
                'auth_user_id': identity,
                'senha': password if get_current_database_mode() != DatabaseMode.SUPABASE else None,
                'must_change_password': True,
                'session_version': int(current.get('session_version') or 0) + 1,
            })
        except Exception:
            if created_identity:
                try:
                    from nistiprint_shared.services.supabase_auth_service import supabase_auth
                    supabase_auth.delete_user(identity)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Falha ao limpar identidade Auth criada durante reativação.')
            raise

        _audit('USUARIO_REATIVADO', 'Conta reativada com redefinição de senha temporária.', usuario_id, get_current_user(), 'usuario',
               before={'ativo': False, 'must_change_password': current.get('must_change_password')},
               after={'ativo': True, 'must_change_password': True, 'auth_user_id': bool(identity)})
        return jsonify({'success': True, 'message': 'Usuário reativado. A senha deve ser trocada no próximo acesso.', 'usuario': _with_access_status(updated)})
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Falha ao reativar usuário %s.', usuario_id)
        return jsonify({'success': False, 'error': 'Não foi possível reativar o usuário.'}), 400





