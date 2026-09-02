from datetime import datetime, timedelta
import os

from flask import jsonify, redirect, request, url_for

from routes.auth import admin_required, login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)
from nistiprint_shared.services.integracao_canal_service import (
    integracao_canal_service,
)
from nistiprint_shared.services.integration_app_profile_service import (
    integration_app_profile_service,
)
from nistiprint_shared.services.integration_credentials_service import (
    integration_credentials_service,
)
from nistiprint_shared.services.integration_provider_registry import (
    get_provider_spec,
    list_provider_specs,
)
from nistiprint_shared.services.integration_module_service import (
    integration_module_service,
)
from nistiprint_shared.services.integration_secret_service import (
    integration_secret_service,
)
from nistiprint_shared.services.installed_integration_service import (
    installed_integration_service,
)
from nistiprint_shared.services.marketplace_account_identity import (
    account_identity_kind,
    merge_account_identity_config,
    normalize_account_identifier,
)
from nistiprint_shared.services.oauth_authorization_session_service import (
    OAuthSessionError,
    oauth_authorization_session_service,
)
from nistiprint_shared.services.platform_api_service import platform_api_service
from nistiprint_shared.services.platform_auth_service import platform_auth_service
from nistiprint_shared.services.token_manager.firebase_projection import (
    bling_firebase_projection_service,
)
from .marketplace_api_base import marketplace_api_bp
from utils.api_response import ApiResponse


def _public_installation(inst):
    return integration_credentials_service.sanitize_installation(
        {**inst.to_dict(), "id": inst.id}
    )


def _auth_payload_for_test(inst):
    return credential_resolver_service.hydrate_integration(
        {**inst.to_dict(), "id": inst.id}
    )


def _auth_update_payload(inst, platform, tokens, explicit_identifier=None):
    identifier = platform_auth_service.resolve_account_identity(
        platform,
        tokens,
        explicit_identifier=explicit_identifier,
    )
    config = merge_account_identity_config(
        inst.config or {},
        platform,
        identifier,
        source="oauth" if identifier else "manual",
        kind=account_identity_kind(platform),
    )
    credentials = {**(inst.credentials or {})}
    credentials.pop("access_token", None)
    credentials.pop("refresh_token", None)
    credentials["expires_in"] = tokens.get("expires_in")
    if identifier:
        credentials[account_identity_kind(platform)] = identifier
        if platform == "shopee" or "shopee" in str(platform):
            credentials["shop_id"] = identifier
        if platform == "mercadolivre":
            credentials["user_id"] = identifier

    return {
        "access_token": None,
        "refresh_token": None,
        "expires_at": (
            datetime.utcnow() + timedelta(seconds=tokens.get("expires_in") or 0)
        ).isoformat(),
        "credentials": credentials,
        "config": config,
        "sync_status": "active",
        "is_active": True,
    }


def _callback_redirect_url(platform):
    if os.environ.get("PUBLIC_URL"):
        return (
            f"{os.environ.get('PUBLIC_URL', '').rstrip('/')}"
            f"{url_for('marketplace_api.auth_callback', platform=platform)}"
        )
    return url_for("marketplace_api.auth_callback", platform=platform, _external=True)


def _extract_manual_account_identifier(module_id, payload):
    if not isinstance(payload, dict):
        return None
    kind = account_identity_kind(module_id)
    account_identifiers = payload.get('account_identifiers') or {}
    return normalize_account_identifier(
        account_identifiers.get('primary')
        or payload.get(kind)
        or payload.get('shop_id')
        or payload.get('user_id')
        or payload.get('seller_id')
        or payload.get('account_id')
    )


def _normalize_marketplace_update_payload(inst, update_data):
    payload = dict(update_data or {})
    module_id = str(inst.module_id or '')
    if not module_id or module_id == 'bling':
        return payload

    config = dict(payload.get('config') or inst.config or {})
    credentials = dict(payload.get('credentials') or inst.credentials or {})
    manual_identifier = (
        _extract_manual_account_identifier(module_id, payload.get('config') or {})
        or _extract_manual_account_identifier(module_id, payload.get('credentials') or {})
        or _extract_manual_account_identifier(module_id, payload)
    )
    if not manual_identifier:
        return payload

    kind = account_identity_kind(module_id)
    payload['config'] = merge_account_identity_config(
        config,
        module_id,
        manual_identifier,
        source='manual',
        kind=kind,
    )
    credentials[kind] = manual_identifier
    if kind == 'shop_id':
        credentials['shop_id'] = manual_identifier
    if kind == 'user_id':
        credentials['user_id'] = manual_identifier
    payload['credentials'] = credentials
    return payload


def _persist_oauth_tokens(instance_id, tokens):
    credential_resolver_service.persist_installation_tokens(instance_id, tokens)


@marketplace_api_bp.route("/auth/init/<module_id>", methods=["POST"])
@login_required
def init_auth(module_id):
    try:
        data = request.get_json(silent=True) or {}
        instance_id = data.get("instance_id")
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst:
            return jsonify({"error": "Instalacao nao encontrada"}), 404

        hydrated = credential_resolver_service.hydrate_integration(
            {**inst.to_dict(), "id": inst.id}
        )
        context = credential_resolver_service.resolve_for_installation(hydrated)
        if not context.app_profile:
            return (
                jsonify(
                    {"error": "Nenhum app profile ativo encontrado para este modulo."}
                ),
                400,
            )

        redirect_uri = context.redirect_uri or _callback_redirect_url(module_id)
        code_verifier = None
        code_challenge = None
        if module_id in {"mercadolivre", "bling"}:
            code_verifier, code_challenge = platform_auth_service.generate_pkce_pair()

        state, _session = oauth_authorization_session_service.create_session(
            module_id=module_id,
            app_profile_id=context.app_profile["id"],
            installed_integration_id=inst.id,
            redirect_uri=redirect_uri,
            return_to=data.get("return_to") or "/configuracoes/integracoes",
            code_verifier=code_verifier,
        )
        auth_url = platform_auth_service.generate_auth_url(
            module_id,
            context,
            redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )
        if not auth_url:
            return jsonify({"error": "URL invalida"}), 400
        return jsonify({"auth_url": auth_url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/auth/exchange/<platform>", methods=["POST"])
def auth_exchange_manual(platform):
    return (
        jsonify(
            {"error": "Fluxo manual descontinuado. Use o callback OAuth normal."}
        ),
        410,
    )


@marketplace_api_bp.route("/auth/callback/<platform>", methods=["GET"])
def auth_callback(platform):
    try:
        code = request.args.get("code")
        state = request.args.get("state")
        shop_id = request.args.get("shop_id")
        if not code or not state:
            return "Error", 400

        session_row = oauth_authorization_session_service.get_session_by_state(
            platform, state
        )
        inst = installed_integration_service.get_installed_by_id(
            session_row["installed_integration_id"]
        )
        if not inst:
            oauth_authorization_session_service.mark_error(
                session_row["id"], "Instalacao nao encontrada"
            )
            return "Error", 404

        hydrated = credential_resolver_service.hydrate_integration(
            {**inst.to_dict(), "id": inst.id}
        )
        context = credential_resolver_service.resolve_for_installation(hydrated)
        tokens = platform_auth_service.exchange_code_for_token(
            platform,
            context,
            code,
            shop_id,
            redirect_uri=session_row.get("redirect_uri"),
            code_verifier=oauth_authorization_session_service.decode_code_verifier(
                session_row
            ),
        )
        _persist_oauth_tokens(inst.id, tokens)
        installed_integration_service.update_installed(
            inst.id,
            _auth_update_payload(inst, platform, tokens, explicit_identifier=shop_id),
        )
        if str(platform or "").lower() == "bling":
            bling_firebase_projection_service.publish_installation_by_id(inst.id)
        oauth_authorization_session_service.mark_consumed(session_row["id"])
        return_to = session_row.get("return_to") or "/configuracoes/integracoes"
        return redirect(
            f"{request.url_root.rstrip('/')}{return_to}"
            f"?status=success&platform={platform}"
        )
    except OAuthSessionError as exc:
        return str(exc), 400
    except Exception as exc:
        try:
            if "session_row" in locals():
                oauth_authorization_session_service.mark_error(
                    session_row["id"], str(exc)
                )
        except Exception:
            pass
        return str(exc), 500


@marketplace_api_bp.route("/modules", methods=["GET"])
def get_available_modules():
    try:
        cat, tags = request.args.get("category"), request.args.get("tags")
        modules = (
            integration_module_service.get_modules_by_category(cat)
            if cat
            else (
                integration_module_service.get_modules_by_tags(tags.split(","))
                if tags
                else integration_module_service.get_all_modules()
            )
        )
        return jsonify({"modules": [{**m.to_dict(), "id": m.id} for m in modules]}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/modules/<module_id>", methods=["GET"])
def get_module_details(module_id):
    mod = integration_module_service.get_module_by_id(module_id)
    if mod:
        return jsonify({"module": {**mod.to_dict(), "id": mod.id}})
    return jsonify({"error": "Not found"}), 404


@marketplace_api_bp.route("/install", methods=["POST"])
@login_required
def install_module():
    try:
        data = request.get_json()

        if not all([data.get("module_id"), data.get("instance_name"), data.get("user_id")]):
            return (
                jsonify(
                    {
                        "error": (
                            "Faltando campos obrigatorios: module_id, instance_name, "
                            "user_id"
                        )
                    }
                ),
                400,
            )

        module = integration_module_service.get_module_by_id(data["module_id"])
        is_dummy_module = bool(
            module
            and (
                module.auth_flow == "dummy"
                or (module.data_mapping_spec or {}).get("dummy") is True
            )
        )
        install_config = dict(data.get("config") or {})
        if is_dummy_module:
            install_config.update(
                {
                    "dummy": True,
                    "is_placeholder": True,
                    "capabilities": {
                        **(install_config.get("capabilities") or {}),
                        "order_import": "erp_bling",
                        "order_update": "erp_bling",
                        "invoicing": "erp_bling",
                    },
                }
            )

        instance_id = installed_integration_service.install_module(
            user_id=data["user_id"],
            module_id=data["module_id"],
            instance_name=data["instance_name"],
            config=install_config,
            credentials=data.get("credentials", {}),
            instance_color=data.get("instance_color", "#64748b"),
            description=data.get("description"),
        )

        update_fields = {}
        # Vincular o aplicativo OAuth na propria instalacao. Sem isto, a
        # instalacao nasce sem `app_profile_id` e, num modulo com mais de um
        # aplicativo ativo, qualquer uso de credencial falha com
        # `app_profile_ambiguous` ate alguem vincular pela tela.
        if data.get("app_profile_id"):
            profile = integration_app_profile_service.get_profile(data["app_profile_id"])
            if not profile:
                return jsonify({"error": "app_profile_id inexistente"}), 400
            if str(profile.get("module_id")) != str(data["module_id"]):
                return (
                    jsonify(
                        {
                            "error": (
                                "app_profile_id pertence ao modulo "
                                f"{profile.get('module_id')}, nao a {data['module_id']}"
                            )
                        }
                    ),
                    400,
                )
            update_fields["app_profile_id"] = profile["id"]
        if data.get("parent_integration_id"):
            update_fields["parent_integration_id"] = data.get("parent_integration_id")
        if "is_default" in data:
            update_fields["is_default"] = bool(data.get("is_default"))
        if data.get("functional_scopes"):
            update_fields["functional_scopes"] = data.get("functional_scopes")
        elif is_dummy_module:
            update_fields["functional_scopes"] = [
                "ORDER_IMPORT",
                "ORDER_UPDATE",
                "INVOICING",
            ]

        if update_fields:
            installed_integration_service.update_installed(instance_id, update_fields)

        try:
            res = (
                supabase_db.client.table("plataformas")
                .select("id, nome")
                .ilike("nome", f"%{data['module_id']}%")
                .limit(1)
                .execute()
            )
            if res.data:
                plataforma = res.data[0]
                res_canal = (
                    supabase_db.client.table("canais_venda")
                    .select("id")
                    .eq("nome", data["instance_name"])
                    .execute()
                )
                canal_id = (
                    res_canal.data[0]["id"]
                    if res_canal.data
                    else supabase_db.client.table("canais_venda")
                    .insert(
                        {
                            "nome": data["instance_name"],
                            "slug": (
                                f"{data['module_id']}-{int(datetime.utcnow().timestamp())}"
                            ),
                            "plataforma_id": plataforma["id"],
                            "ativo": True,
                            "color": data.get("instance_color", "#64748b"),
                        }
                    )
                    .execute()
                    .data[0]["id"]
                )

                if install_config.get("bling_loja_id"):
                    try:
                        integracao_canal_service.criar_vinculo(
                            canal_venda_id=canal_id,
                            bling_loja_id=int(install_config["bling_loja_id"]),
                            plataforma_nome=plataforma["nome"],
                            integration_id=int(instance_id),
                            is_primary=False,
                            config_json={},
                        )
                    except Exception:
                        pass
        except Exception as exc:
            print(f"Erro no provisionamento automatico: {exc}")

        inst = installed_integration_service.get_installed_by_id(instance_id)
        return (
            jsonify(
                {
                    "success": True,
                    "instance_id": instance_id,
                    "installation": _public_installation(inst),
                }
            ),
            201,
        )
    except Exception as exc:
        print(f"Erro na instalacao: {exc}")
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/installed", methods=["GET"])
@login_required
def get_installed_integrations():
    try:
        user_id = request.args.get("user_id")
        module_id = request.args.get("module_id")
        category = request.args.get("category")

        insts = installed_integration_service.get_all_installed(user_id=user_id)

        if module_id:
            insts = [i for i in insts if i.module_id == module_id]

        if category:
            modules = integration_module_service.get_modules_by_category(category)
            module_ids = [m.id for m in modules]
            insts = [i for i in insts if i.module_id in module_ids]

        return jsonify({"installations": [_public_installation(i) for i in insts]})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/installed/<instance_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def installed_crud(instance_id):
    if request.method == "GET":
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst:
            return jsonify({"error": "Nao encontrado"}), 404
        return jsonify({"installation": _public_installation(inst)})

    if request.method == "PUT":
        data = request.get_json()
        update_data = {}
        allowed_fields = {
            "config",
            "credentials",
            "is_active",
            "instance_name",
            "parent_integration_id",
            "is_default",
            "functional_scopes",
            "instance_color",
            "description",
            "app_profile_id",
        }

        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if update_data:
            update_data = _normalize_marketplace_update_payload(inst, update_data)
            installed_integration_service.update_installed(instance_id, update_data)

        inst = installed_integration_service.get_installed_by_id(instance_id)
        return jsonify({"success": True, "installation": _public_installation(inst)})

    if request.method == "DELETE":
        installed_integration_service.uninstall(instance_id)
        return jsonify({"success": True})

    return jsonify({"error": "Metodo nao permitido"}), 405


@marketplace_api_bp.route("/bling/config-helpers/<instance_id>", methods=["GET"])
@login_required
def get_bling_config_helpers(instance_id):
    try:
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst or inst.module_id != "bling":
            return jsonify({"error": "Instancia Bling nao encontrada"}), 404

        from nistiprint_shared.services.bling.bling_client_updated import BlingClient

        account_data = credential_resolver_service.hydrate_integration(
            {**inst.to_dict(), "id": inst.id}
        )
        client = BlingClient(account_data)

        return jsonify(
            {
                "situacoes": client.get_situacoes(modulo="vendas"),
                "lojas": client.get_stores(),
            }
        ), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/bling/orders/search", methods=["GET"])
@login_required
def search_bling_orders():
    try:
        instance_id = request.args.get("instance_id")
        status_id = request.args.get("status_id")
        store_id = request.args.get("store_id")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        if not instance_id:
            return jsonify({"error": "instance_id e obrigatorio"}), 400

        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst or inst.module_id != "bling":
            return jsonify({"error": "Instancia Bling nao encontrada"}), 404

        from nistiprint_shared.services.bling.bling_client_updated import BlingClient

        account_data = credential_resolver_service.hydrate_integration(
            {**inst.to_dict(), "id": inst.id}
        )
        client = BlingClient(account_data)

        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.utcnow().strftime("%Y-%m-%d")

        orders = client.get_orders_by_status(
            status_id=status_id,
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
        )

        return jsonify({"orders": orders}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/bling/orders/import", methods=["POST"])
@login_required
def import_bling_orders():
    try:
        data = request.get_json()
        instance_id = data.get("instance_id")
        order_ids = data.get("order_ids", [])

        if not instance_id or not order_ids:
            return jsonify({"error": "instance_id e order_ids sao obrigatorios"}), 400

        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst or inst.module_id != "bling":
            return jsonify({"error": "Instancia Bling nao encontrada"}), 404

        from nistiprint_shared.services.bling.bling_client_updated import BlingClient
        from nistiprint_shared.services.bling_order_processing_service import (
            BlingOrderProcessingService,
        )
        from nistiprint_shared.services.order_sync_service import order_sync_service

        account_data = credential_resolver_service.hydrate_integration(
            {**inst.to_dict(), "id": inst.id}
        )
        client = BlingClient(account_data)
        processor = BlingOrderProcessingService()

        results = []
        for oid in order_ids:
            try:
                full_order = client.get_order(oid)
                if not full_order:
                    results.append(
                        {
                            "id": oid,
                            "status": "error",
                            "message": "Nao foi possivel obter detalhes do pedido",
                        }
                    )
                    continue

                sync_result = order_sync_service.sync_bling_order(full_order)
                processor._save_order_to_db(full_order)

                results.append(
                    {
                        "id": oid,
                        "status": "success",
                        "numero": full_order.get("numero"),
                        "internal_id": sync_result.get("id") if sync_result else None,
                    }
                )
            except Exception as oid_err:
                results.append(
                    {"id": oid, "status": "error", "message": str(oid_err)}
                )

        return jsonify({"results": results}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/installed/<instance_id>/test", methods=["POST"])
@login_required
def test_integration(instance_id):
    inst = installed_integration_service.get_installed_by_id(instance_id)
    if not inst:
        return jsonify({"error": "Not found"}), 404
    payload = _auth_payload_for_test(inst)
    module = integration_module_service.get_module_by_id(inst.module_id)
    test_path = module.data_mapping_spec.get("test_endpoint") if module else None
    driver_result = platform_api_service.test_connection(
        payload, module_id=inst.module_id, path=test_path
    )
    if not driver_result.get("error"):
        return jsonify({"success": True, "result": driver_result})
    return jsonify(
        {
            "success": True,
            "result": platform_auth_service.call_test_endpoint(inst.module_id, payload),
        }
    )


@marketplace_api_bp.route("/installed/<instance_id>/sync", methods=["POST"])
@login_required
def trigger_sync(instance_id):
    installed_integration_service.update_sync_status(instance_id, "syncing")
    installed_integration_service.update_sync_status(instance_id, "success")
    return jsonify({"success": True})


@marketplace_api_bp.route("/installed/<instance_id>/renew", methods=["POST"])
@login_required
def renew_token(instance_id):
    try:
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst:
            return jsonify({"error": "Not found"}), 404
        integration_credentials_service.ensure_refresh_allowed(
            {**inst.to_dict(), "id": inst.id}
        )
        installed_integration_service.renew_integration_token(
            instance_id, execution_mode="manual"
        )
        refreshed = installed_integration_service.get_installed_by_id(instance_id)
        return jsonify({"status": "success", "installation": _public_installation(refreshed)})
    except Exception as exc:
        installed_integration_service.update_installed(
            instance_id, {"refresh_error": str(exc)}
        )
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/installed/<instance_id>/sync-account-identity", methods=["POST"])
@login_required
def sync_account_identity(instance_id):
    try:
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst:
            return jsonify({"error": "Not found"}), 404
        data = request.get_json(silent=True) or {}
        result = installed_integration_service.sync_account_identity(
            instance_id,
            explicit_identifier=data.get('account_identifier'),
            source=data.get('source') or 'manual_sync',
        )
        installation = result.get('installation')
        return jsonify(
            {
                "success": True,
                "account_identifier": result.get('identifier'),
                "account_identifier_kind": result.get('kind'),
                "installation": _public_installation(installation) if installation else None,
            }
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@marketplace_api_bp.route("/installed/<instance_id>/credential-status", methods=["GET"])
@login_required
def get_credential_status(instance_id):
    inst = installed_integration_service.get_installed_by_id(instance_id)
    if not inst:
        return jsonify({"error": "Not found"}), 404
    return jsonify(
        {
            "credential_status": integration_credentials_service.public_view(
                {**inst.to_dict(), "id": inst.id}
            )
        }
    )


@marketplace_api_bp.route("/installed/<instance_id>/app-profile", methods=["GET", "PUT"])
@admin_required
def manage_installation_app_profile(instance_id):
    inst = installed_integration_service.get_installed_by_id(instance_id)
    if not inst:
        return jsonify({"error": "Not found"}), 404

    if request.method == "GET":
        profiles = integration_app_profile_service.list_profiles(module_id=inst.module_id)
        return jsonify(
            {
                "installation_id": instance_id,
                "module_id": inst.module_id,
                "app_profile_id": inst.app_profile_id,
                "profiles": profiles,
            }
        )

    data = request.get_json(silent=True) or {}
    app_profile_id = data.get("app_profile_id")

    if app_profile_id in (None, "", "none"):
        installed_integration_service.update_installed(
            instance_id, {"app_profile_id": None}
        )
    else:
        profile = integration_app_profile_service.get_profile(app_profile_id)
        if not profile:
            return jsonify({"error": "App profile not found"}), 404
        if str(profile.get("module_id") or "") != str(inst.module_id or ""):
            return (
                jsonify(
                    {
                        "error": "App profile incompatível com o módulo desta instalação"
                    }
                ),
                400,
            )
        if not profile.get("is_active", True):
            return jsonify({"error": "App profile inativo"}), 400

        installed_integration_service.update_installed(
            instance_id, {"app_profile_id": profile["id"]}
        )

    updated = installed_integration_service.get_installed_by_id(instance_id)
    return jsonify(
        {
            "success": True,
            "installation": _public_installation(updated),
        }
    )


@marketplace_api_bp.route("/installed/<instance_id>/config", methods=["PUT"])
@login_required
def update_integration_config(instance_id):
    inst = installed_integration_service.get_installed_by_id(instance_id)
    if not inst:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json()
    config_update = data.get("config", {})
    current_config = inst.config or {}
    updated_config = {**current_config, **config_update}

    update_payload = _normalize_marketplace_update_payload(
        inst,
        {"config": updated_config},
    )
    installed_integration_service.update_installed(instance_id, update_payload)
    refreshed = installed_integration_service.get_installed_by_id(instance_id)
    return jsonify({"success": True, "config": refreshed.config if refreshed else update_payload.get("config", {})})


@marketplace_api_bp.route("/app-profiles", methods=["GET", "POST"])
@admin_required
def app_profiles():
    if request.method == "GET":
        module_id = request.args.get("module_id")
        return jsonify(
            {"profiles": integration_app_profile_service.list_profiles(module_id=module_id)}
        )

    data = request.get_json(silent=True) or {}
    provider_spec = get_provider_spec(data.get("module_id"))
    if not provider_spec:
        return jsonify({"error": "Modulo sem spec de credenciais"}), 400
    payload = {
        "module_id": data.get("module_id"),
        "name": data.get("name"),
        "environment": data.get("environment") or "production",
        "redirect_uri": data.get("redirect_uri"),
        "auth_base_url": data.get("auth_base_url"),
        "token_url": data.get("token_url"),
        "is_default": bool(data.get("is_default", False)),
        "is_active": bool(data.get("is_active", True)),
    }
    secrets_payload = {
        key: value
        for key, value in {
            field.secret_kind: data.get(field.secret_kind)
            for field in provider_spec.app_profile_secret_fields
        }.items()
        if value not in (None, "")
    }
    profile = integration_app_profile_service.create_profile(
        payload, secrets=secrets_payload
    )
    return jsonify({"profile": profile}), 201


@marketplace_api_bp.route("/app-profile-specs", methods=["GET"])
@admin_required
def app_profile_specs():
    module_id = request.args.get("module_id")
    if module_id:
        spec = get_provider_spec(module_id)
        return jsonify({"spec": spec.to_dict() if spec else None})
    return jsonify({"specs": list_provider_specs()})


@marketplace_api_bp.route("/app-profiles/<profile_id>", methods=["GET", "PUT"])
@admin_required
def app_profile_detail(profile_id):
    if request.method == "GET":
        profile = integration_app_profile_service.get_profile(profile_id)
        if not profile:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"profile": profile})

    data = request.get_json(silent=True) or {}
    module_id = data.get("module_id")
    current_profile = integration_app_profile_service.get_profile(profile_id)
    provider_spec = get_provider_spec(module_id or (current_profile or {}).get("module_id"))
    if not current_profile:
        return jsonify({"error": "Not found"}), 404
    if not provider_spec:
        return jsonify({"error": "Modulo sem spec de credenciais"}), 400
    payload = {
        key: value
        for key, value in {
            "name": data.get("name"),
            "environment": data.get("environment"),
            "redirect_uri": data.get("redirect_uri"),
            "auth_base_url": data.get("auth_base_url"),
            "token_url": data.get("token_url"),
            "is_default": data.get("is_default"),
            "is_active": data.get("is_active"),
        }.items()
        if value is not None
    }
    secrets_payload = {
        key: value
        for key, value in {
            field.secret_kind: data.get(field.secret_kind)
            for field in provider_spec.app_profile_secret_fields
        }.items()
        if value not in (None, "")
    }
    profile = integration_app_profile_service.update_profile(
        profile_id, payload, secrets=secrets_payload
    )
    if not profile:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"profile": profile})


@marketplace_api_bp.route("/admin/backfill-secrets", methods=["POST"])
@admin_required
def backfill_secrets():
    insts = installed_integration_service.get_all_installed()
    migrated_secrets = 0
    linked_profiles = 0
    for inst in insts:
        installation = {**inst.to_dict(), "id": inst.id}

        if not installation.get("app_profile_id"):
            default_profile = integration_app_profile_service.get_default_profile(
                installation.get("module_id")
            )
            if default_profile:
                installed_integration_service.update_installed(
                    inst.id, {"app_profile_id": default_profile["id"]}
                )
                linked_profiles += 1

        for kind in ("access_token", "refresh_token"):
            value = installation.get(kind) or (installation.get("credentials") or {}).get(
                kind
            )
            if value not in (None, ""):
                integration_secret_service.put_secret(
                    "installed_integration", inst.id, kind, value
                )
                migrated_secrets += 1
    return jsonify(
        {
            "status": "success",
            "migrated": migrated_secrets,
            "linked_profiles": linked_profiles,
        }
    )


@marketplace_api_bp.route("/orders/list", methods=["POST"])
def get_orders_list():
    data = request.get_json(silent=True) or {}
    result = platform_api_service.get_orders_list(
        instance_id=data.get("instance_id") or request.args.get("instance_id"),
        module_id=data.get("module_id") or request.args.get("module_id") or "shopee",
        filters=data.get("filters", {}),
    )
    if isinstance(result, list) and result and "error" in result[0]:
        return ApiResponse.error(
            message=result[0]["error"], errors=result[0], status_code=500
        )
    return ApiResponse.success(data=result)


@marketplace_api_bp.route("/orders/detail", methods=["POST"])
def get_order_detail():
    data = request.get_json(silent=True) or {}
    order_sn = data.get("order_sn_list") or request.args.get("order_sn_list")
    if not order_sn:
        return ApiResponse.error(message="Required", status_code=400)
    result = platform_api_service.get_order_detail(
        [sn.strip() for sn in order_sn.split(",") if sn.strip()],
        instance_id=data.get("instance_id") or request.args.get("instance_id"),
        module_id=data.get("module_id") or request.args.get("module_id") or "shopee",
    )
    if result.get("error") and result.get("error") != "":
        return ApiResponse.error(
            message=result["error"], errors=result, status_code=500
        )
    return ApiResponse.success(data=result)


@marketplace_api_bp.route("/instances", methods=["GET"])
@login_required
def get_marketplace_instances():
    try:
        active = request.args.get("active", "false").lower() == "true"
        insts = installed_integration_service.get_all_installed()
        insts = [i for i in insts if i.module_id != "bling"]
        if active:
            insts = [i for i in insts if i.is_active]

        return jsonify(
            {
                "data": [
                    {
                        "id": i.id,
                        "module_id": i.module_id,
                        "instance_name": i.instance_name,
                        "is_active": i.is_active,
                    }
                    for i in insts
                ]
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
