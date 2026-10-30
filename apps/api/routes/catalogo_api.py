"""Catalog and listing APIs; database RPCs own the transactional writes."""
import logging

from flask import Blueprint, jsonify, request
from routes.auth import get_current_user, require_request_permission
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.catalogo_familia_service import CatalogoFamiliaService
from nistiprint_shared.services.anuncio_service import AnuncioService
from utils.api_response import ApiResponse

catalogo_bp = Blueprint('catalogo_api', __name__, url_prefix='/api/v2')
logger = logging.getLogger(__name__)


def _permission(resource, action):
    return require_request_permission(resource, action)


def _error(exc):
    code = getattr(exc, 'code', None) or getattr(exc, 'sqlstate', None)
    if code in {'40001', 'CATALOG_VERSION_CONFLICT'}:
        return jsonify(success=False, error='O cadastro foi alterado por outra pessoa. Atualize os dados e tente novamente.'), 409
    if code in {'22023', '23505', '23503', 'P0002'} or isinstance(exc, ValueError):
        return jsonify(success=False, error=str(exc)), 422
    logger.exception('Falha no catálogo (%s)', type(exc).__name__)
    return jsonify(success=False, error='Não foi possível concluir a operação de catálogo.'), 503


@catalogo_bp.get('/produtos/<int:product_id>/familia')
def family_get(product_id):
    denied = _permission('produtos', 'ler')
    if denied:
        return denied
    try:
        data = CatalogoFamiliaService(supabase_db).get(product_id)
        if data is None:
            return jsonify(success=False, error='Produto não encontrado.'), 404
        return ApiResponse.success(data)
    except Exception as exc:
        return _error(exc)


@catalogo_bp.put('/produtos/<int:product_id>/familia')
def family_save(product_id):
    denied = _permission('produtos', 'editar')
    if denied:
        return denied
    user = get_current_user() or {}
    try:
        data = CatalogoFamiliaService(supabase_db).save(product_id, request.get_json(silent=True), user.get('id'))
        return ApiResponse.success(data)
    except Exception as exc:
        return _error(exc)


@catalogo_bp.post('/integracoes/<int:integration_id>/catalogo/sincronizar')
def catalog_sync(integration_id):
    denied = _permission('produtos', 'editar')
    if denied:
        return denied
    try:
        rows = supabase_db.table('installed_integrations').select('id').eq('id', integration_id).eq('is_active', True).limit(1).execute().data or []
        if not rows:
            return jsonify(success=False, error='Conta de integração não encontrada ou inativa.'), 404
        from nistiprint_shared.services.celery_app import celery_app
        from nistiprint_shared.services.catalog_operations import create_operation
        operation_id = create_operation((get_current_user() or {})['id'],integration_id)
        task = celery_app.send_task('tasks.catalog_tasks.sync_account', args=[integration_id,operation_id], queue='marketplace_analytics')
        return ApiResponse.success({'task_id': task.id,'operation_id':operation_id}, status_code=202)
    except Exception as exc:
        return _error(exc)


@catalogo_bp.get('/integracoes/<int:integration_id>/estatisticas/capacidades')
def integration_capabilities(integration_id):
    denied = _permission('produtos', 'ler')
    if denied:
        return denied
    try:
        rows = supabase_db.table('installed_integrations').select('id,platform_slug,module_id,is_active').eq('id', integration_id).limit(1).execute().data or []
        if not rows:
            return jsonify(success=False, error='Conta de integração não encontrada.'), 404
        from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService
        catalog = MarketplaceCatalogSyncService(supabase_db).capabilities(rows[0])
        collections = supabase_db.table('gestao_coletas').select('capability,status,checked_at,error_code,enabled').eq('account_id', integration_id).execute().data or []
        return ApiResponse.success({'integration_id': integration_id, 'catalog': catalog, 'statistics': collections})
    except Exception as exc:
        return _error(exc)


@catalogo_bp.post('/integracoes/<int:integration_id>/catalogo/reconciliar')
def catalog_reconcile(integration_id):
    denied = _permission('produtos','editar')
    if denied:
        return denied
    try:
        rows = supabase_db.table('installed_integrations').select('id').eq('id',integration_id).eq('is_active',True).execute().data or []
        if not rows:
            return ApiResponse.error('Conta não encontrada ou inativa.',404)
        from nistiprint_shared.services.catalog_operations import create_operation
        from nistiprint_shared.services.celery_app import celery_app
        operation_id = create_operation(get_current_user()['id'],integration_id,'Reconciliação dos anúncios')
        task = celery_app.send_task('tasks.catalog_tasks.reconcile_account',args=[integration_id,0,operation_id],queue='marketplace_analytics')
        return ApiResponse.success({'task_id':task.id,'operation_id':operation_id},status_code=202)
    except Exception as exc:
        return _error(exc)


@catalogo_bp.get('/produtos/<int:product_id>/anuncios')
def product_announcements(product_id):
    denied = _permission('produtos', 'ler')
    if denied:
        return denied
    try:
        return ApiResponse.success(AnuncioService(supabase_db).for_product(product_id))
    except Exception as exc:
        return _error(exc)


@catalogo_bp.get('/anuncios')
def announcement_list():
    denied = _permission('produtos', 'ler')
    if denied:
        return denied
    try:
        data = AnuncioService(supabase_db).list(
            page=request.args.get('page', 1, type=int), per_page=request.args.get('per_page', 50, type=int),
            integration_id=request.args.get('integration_id', type=int), produto_id=request.args.get('produto_id', type=int),
            status=request.args.get('status'), query=request.args.get('q'), relationship=request.args.get('relationship'))
        return ApiResponse.success(data)
    except Exception as exc:
        return _error(exc)


@catalogo_bp.get('/anuncios/<int:announcement_id>')
def announcement_get(announcement_id):
    denied = _permission('produtos', 'ler')
    if denied:
        return denied
    try:
        data = AnuncioService(supabase_db).get(announcement_id)
        if data is None:
            return jsonify(success=False, error='Anúncio não encontrado.'), 404
        return ApiResponse.success(data)
    except Exception as exc:
        return _error(exc)


@catalogo_bp.put('/anuncios/unidades/<int:unit_id>/vinculo')
def announcement_link(unit_id):
    denied = _permission('produtos', 'editar')
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get('integration_id')) is not int or type(data.get('expected_version')) is not int:
        return jsonify(success=False, error='Informe integration_id e expected_version.'), 400
    product_id = data.get('produto_id')
    if product_id is not None and (not isinstance(product_id, int) or product_id <= 0):
        return jsonify(success=False, error='produto_id deve ser inteiro positivo ou null.'), 400
    if not isinstance(data.get('motivo'), str) or not data['motivo'].strip():
        return jsonify(success=False, error='Informe o motivo do vínculo.'), 400
    try:
        units = supabase_db.table('produto_anuncios').select('id,integration_id,anuncio_id,vinculo_versao').eq('id', unit_id).limit(1).execute().data or []
        if not units or units[0].get('integration_id') != data['integration_id']:
            return jsonify(success=False, error='A unidade não pertence à conta informada.'), 404
        user = get_current_user() or {}
        result = supabase_db.rpc('marketplace_anuncio_vincular', {
            'p_unidade_id': unit_id, 'p_produto_id': product_id, 'p_motivo': data['motivo'].strip(),
            'p_origem': 'manual', 'p_usuario': None, 'p_actor': user.get('id'), 'p_expected_version': data['expected_version'],
        }).execute().data
        return ApiResponse.success(result)
    except Exception as exc:
        return _error(exc)
