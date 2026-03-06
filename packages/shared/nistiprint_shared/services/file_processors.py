import logging
import pandas as pd
import json
from datetime import datetime
from nistiprint_shared.utils import apply_date_filter, apply_miolo_fixes, fix_sku_devocional_amazon, generate_ids_chunks, prepare_ml_file, process_string, fix_amazon_25_to_26
from ..constants import COLUMNS, COLUMN_SHIP_DATE, CAPAS_GROUP
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.shopee_orders import ShopeeOrders
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.order_tracker_service import order_tracker_service
from nistiprint_shared.services.app_config_service import app_config_service

def resolve_miolo(external_sku, default_slice=10):
    if not isinstance(external_sku, str):
        return str(external_sku)[:default_slice] if external_sku else '-'
    
    # Default fallback (existing logic)
    # We slice the SKU to get the base code for Miolo fixes
    return external_sku[:default_slice]

def get_miolo_from_bom(product_id):
    """
    Tenta encontrar o componente 'Miolo' na BOM do produto.
    Retorna tanto o nome quanto o ID do produto componente.
    Baseado na configuração 'producao_miolos_category_id' (padrão 6).
    """
    try:
        # Get configured category ID for Miolo
        miolo_cat_id = str(app_config_service.get_config('producao_miolos_category_id') or '6')
        logging.info(f"[DEBUG MIOLo] Buscando miolo para produto ID: {product_id}, categoria esperada: {miolo_cat_id}")

        # Get BOM components
        components = product_service.get_bom_components(str(product_id))
        logging.info(f"[DEBUG MIOLo] Componentes encontrados na BOM: {len(components) if components else 0}")

        for i, comp in enumerate(components or []):
            logging.info(f"[DEBUG MIOLo] Componente {i+1}: ID={comp.get('id')}, Name={comp.get('name')}, Categoria_ID={comp.get('categoria_id')}")
            # Check if component category matches configured Miolo category
            # Convert both to string to be safe
            if str(comp.get('categoria_id')) == miolo_cat_id:
                logging.info(f"[DEBUG MIOLo] Encontrado miolo na BOM: {comp.get('name')} (ID: {comp.get('id')})")
                return comp.get('name'), comp.get('id')

        logging.info(f"[DEBUG MIOLo] Nenhum componente encontrado com categoria {miolo_cat_id}")
        return None, None
    except Exception as e:
        logging.error(f"Erro ao buscar miolo da BOM para produto {product_id}: {e}")
        return None, None

def enrich_orders_with_personalizations(bling_orders_data, platform_name, mode=None):
    """Busca personalizações no banco de dados ativo (Supabase ou MySQL) e anexa aos itens."""
    if not bling_orders_data: return bling_orders_data
    
    if not mode:
        from nistiprint_shared.services.app_config_service import app_config_service
        mode = app_config_service.get_operational_mode()
    
    if mode == 'legacy':
        return enrich_orders_with_personalizations_legacy(bling_orders_data)
    
    return enrich_orders_with_personalizations_supabase(bling_orders_data)

def enrich_orders_with_personalizations_supabase(bling_orders_data):
    """Lógica original de enriquecimento via Supabase."""
    order_sns = [str(o['numeroLoja']) for o in bling_orders_data if o.get('numeroLoja')]
    if not order_sns: return bling_orders_data

    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.models.bling_pedidos import BlingPedidos
    from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
    
    try:
        # 1. Buscar Pedidos Locais (Ponte)
        local_orders = BlingPedidos.query.filter(BlingPedidos.numero_loja.in_(order_sns)).all()
        local_order_map = {o.numero_loja: o for o in local_orders}
        local_order_ids = [o.id for o in local_orders]
        
        local_items = []
        if local_order_ids:
            local_items = BlingPedidoItens.query.filter(BlingPedidoItens.pedido_bling_id.in_(local_order_ids)).all()

        # 2. Busca todas as personalizações
        response = supabase_db.table('personalizacoes_pedido') \
            .select("*") \
            .in_('shopee_order_sn', order_sns) \
            .execute()
        
        if not response.data: return bling_orders_data

        # 3. Indexar Personalizações
        pers_by_item_id = {} # Key: local_item_id
        pers_by_desc = {}    # Key: (order_sn, desc)

        for p in response.data:
            if p.get('item_id'):
                pers_by_item_id[str(p['item_id'])] = p
            
            key = (str(p['shopee_order_sn']), str(p['item_description']).strip())
            if key not in pers_by_desc: pers_by_desc[key] = []
            pers_by_desc[key].append(p)

        # 4. Anexa aos itens
        for order in bling_orders_data:
            sn = str(order['numeroLoja'])
            local_order = local_order_map.get(sn)
            l_items_this_order = [li for li in local_items if li.pedido_bling_id == local_order.id] if local_order else []
            
            for item in order.get('itens', []):
                found_pers_list = []
                if local_order:
                    matched_local_item = next((li for li in l_items_this_order if str(li.codigo) == str(item.get('codigo'))), None)
                    if matched_local_item:
                        pers = pers_by_item_id.get(str(matched_local_item.id))
                        if pers: found_pers_list.append(pers)

                if not found_pers_list:
                    desc = str(item.get('descricao', '')).strip()
                    matches = pers_by_desc.get((sn, desc))
                    if matches: found_pers_list = matches
                
                if found_pers_list:
                    item['personalization_name'] = found_pers_list[0].get('customization_name')
                    item['personalizations'] = found_pers_list
        
        return bling_orders_data
    except Exception as e:
        logging.error(f"Erro ao enriquecer pedidos com personalizações (Supabase): {e}")
        return bling_orders_data

def enrich_orders_with_personalizations_legacy(bling_orders_data):
    """Enriquece pedidos buscando diretamente no MySQL legado."""
    order_sns = [str(o['numeroLoja']) for o in bling_orders_data if o.get('numeroLoja')]
    if not order_sns: return bling_orders_data

    from nistiprint_shared.services.legacy_sync_service import LegacySyncService
    from sqlalchemy import text
    
    try:
        conn = LegacySyncService._get_legacy_connection()
        with conn:
            # 1. Buscar personalizações no MySQL
            query = text("""
                SELECT * FROM order_personalizations 
                WHERE shopee_order_sn IN :sns
            """)
            result = conn.execute(query, {"sns": tuple(order_sns)}).mappings().all()
            personalizations = [dict(row) for row in result]
            
            if not personalizations: return bling_orders_data

            # 2. Buscar pedidos e itens locais no MySQL para ponte de ID
            # Fixed table name to 'bling_pedidos' and 'bling_pedido_itens'
            query_local = text("""
                SELECT p.numeroLoja, i.id as local_item_id, i.codigo as sku
                FROM bling_pedidos p
                JOIN bling_pedido_itens i ON p.id = i.pedido_id
                WHERE p.numeroLoja IN :sns
            """)
            local_map_result = conn.execute(query_local, {"sns": tuple(order_sns)}).mappings().all()
            
            # Bridge Map: (SN, SKU) -> local_item_id
            bridge_map = {(str(row['numeroLoja']), str(row['sku'])): str(row['local_item_id']) for row in local_map_result}

            # 3. Indexar Personalizações
            # Preferred: Index by personalization's record item_id (which maps to local_item_id in MySQL)
            pers_by_item_id = {}
            for p in personalizations:
                iid = str(p['item_id'])
                if iid not in pers_by_item_id: pers_by_item_id[iid] = []
                pers_by_item_id[iid].append(p)

            pers_by_desc = {}
            for p in personalizations:
                key = (str(p['shopee_order_sn']), str(p['item_description']).strip())
                if key not in pers_by_desc: pers_by_desc[key] = []
                pers_by_desc[key].append(p)

            # 4. Anexar aos itens do Bling
            for order in bling_orders_data:
                sn = str(order['numeroLoja'])
                for item in order.get('itens', []):
                    sku = str(item.get('codigo'))
                    found_pers_list = []
                    
                    # Ponte via ID (Legacy DB)
                    local_item_id = bridge_map.get((sn, sku))
                    if local_item_id:
                        matches = pers_by_item_id.get(local_item_id)
                        if matches: found_pers_list = matches
                    
                    # Fallback via Descrição
                    if not found_pers_list:
                        desc = str(item.get('descricao', '')).strip()
                        matches = pers_by_desc.get((sn, desc))
                        if matches: found_pers_list = matches
                    
                    if found_pers_list:
                        item['personalization_name'] = found_pers_list[0].get('customization_name')
                        item['personalizations'] = found_pers_list

        return bling_orders_data
    except Exception as e:
        logging.error(f"Erro ao enriquecer pedidos com personalizações (Legacy): {e}")
        return bling_orders_data

def process_mercadolivre(file, period_filter=None, options=None, bling_client=None):
    bling_orders_id = []
    bling_orders_data = []
    bling_orders_id_numero = {}
    bling_orders_not_found = []
    
    # Read the file
    data = pd.read_excel(file, skiprows=5)
    print(f"[ML DEBUG] Total lines read from file: {len(data)}")

    valid_states = [
        'Pronta para emitir NF-e de venda',
        'Emita a Nota Fiscal eletrônica (NF-e)',
        'Aguardando disponibilidade de estoque',
        'Anúncio sem dados fiscais',
        'Etiqueta pronta para imprimir',
        'Para enviar amanhã'
    ]

    records = data.to_dict('records')
    valid_rows_for_df = []
    
    current_package_rows = []
    
    count_packages_processed = 0
    count_packages_valid = 0
    count_single_valid = 0

    def process_buffered_package(rows):
        nonlocal count_packages_processed, count_packages_valid
        count_packages_processed += 1
        
        # Check validity: At least one row in the package must have a valid state
        is_valid = False
        valid_state_found = None
        for r in rows:
            if r.get('Estado') in valid_states:
                is_valid = True
                valid_state_found = r.get('Estado')
                break
        
        if is_valid:
            count_packages_valid += 1
            
            # 1. Add to DataFrame list (for stats)
            for r in rows:
                sku = r.get('SKU')
                if not pd.isna(sku) and str(sku).strip() != '':
                    valid_rows_for_df.append(r)
            
            # 2. Build Bling Order (for PDF)
            header = rows[0]
            order_id = str(header.get('N.º de venda', ''))
            address = header.get('Endereço', '')
            total_pacote = header.get('Receita por produtos (BRL)')
            
            package_order = {
                "numeroLoja": order_id,
                "numero": order_id,
                "id": order_id,
                "contato": {
                    "nome": header.get('Comprador', ''),
                    "numeroDocumento": header.get('CPF', ''),
                    "endereco": address
                },
                "itens": [],
                "totalProdutos": total_pacote,
                "transporte": { "contato": { "id": None } },
                "formaDeEntrega": header.get('Forma de entrega', ''),
                "hasCustomItem": 0,
                "total_items": 0
            }
            
            for r in rows:
                sku = r.get('SKU')
                if not pd.isna(sku) and str(sku).strip() != '':
                     item = {
                        "codigo": str(sku),
                        "descricao": r.get('Título do anúncio', ''),
                        "quantidade": int(r.get('Unidades', 0)) if not pd.isna(r.get('Unidades')) else 0,
                        "valor": 0,
                        "variacao": r.get('Variação') if not pd.isna(r.get('Variação')) and r.get('Variação') != '' else None,
                        "custom_tag": "",
                        "original_id": str(r.get('N.º de venda', ''))
                    }
                     package_order['itens'].append(item)
            
            bling_orders_data.append(package_order)
            bling_orders_id_numero[order_id] = order_id
            
        else:
            pass

    for i, row in enumerate(records):
        state = str(row.get('Estado', ''))
        total_brl = row.get('Total (BRL)')
        is_total_empty = pd.isna(total_brl) or str(total_brl).strip() == ''

        is_package_header = state.startswith('Pacote de')
        
        if is_package_header:
            if current_package_rows:
                process_buffered_package(current_package_rows)
            current_package_rows = [row]
            
        elif current_package_rows and is_total_empty:
            current_package_rows.append(row)
            
        else:
            if current_package_rows:
                process_buffered_package(current_package_rows)
                current_package_rows = []
            
            if state in valid_states:
                count_single_valid += 1
                valid_rows_for_df.append(row)
                
                order_id = str(row.get('N.º de venda', ''))
                address = row.get('Endereço', '')
                
                order = {
                    "numeroLoja": order_id,
                    "numero": order_id,
                    "id": order_id,
                    "contato": {
                        "nome": row.get('Comprador', ''),
                        "numeroDocumento": row.get('CPF', ''),
                        "endereco": address
                    },
                    "itens": [],
                    "totalProdutos": total_brl,
                    "transporte": { "contato": { "id": None } },
                    "formaDeEntrega": row.get('Forma de entrega', ''),
                    "hasCustomItem": 0,
                    "total_items": 0
                }
                
                item = {
                    "codigo": str(row.get('SKU', '')),
                    "descricao": row.get('Título do anúncio', ''),
                    "quantidade": int(row.get('Unidades', 0)) if not pd.isna(row.get('Unidades')) else 0,
                    "valor": total_brl,
                    "variacao": row.get('Variação') if not pd.isna(row.get('Variação')) and row.get('Variação') != '' else None,
                    "custom_tag": "",
                    "original_id": str(row.get('N.º de venda', ''))
                }
                order['itens'].append(item)
                bling_orders_data.append(order)
                bling_orders_id_numero[order_id] = order_id
            else:
                 pass

    if current_package_rows:
        process_buffered_package(current_package_rows)

    print(f"[ML DEBUG] SUMMARY: Pkgs Processed: {count_packages_processed}, Pkgs Valid: {count_packages_valid}, Singles Valid: {count_single_valid}")
    print(f"[ML DEBUG] Total Orders (Bling Data): {len(bling_orders_data)}")
    print(f"[ML DEBUG] Total Rows for Stats: {len(valid_rows_for_df)}")

    # Create Filtered Data from the collected valid rows
    if valid_rows_for_df:
        filtered_data = pd.DataFrame(valid_rows_for_df)
    else:
        filtered_data = pd.DataFrame(columns=data.columns)

    if not filtered_data.empty:
        filtered_data = filtered_data[COLUMNS['mercadolivre']].copy()
        filtered_data['N.º de venda'] = filtered_data['N.º de venda'].astype(str)

    # --- ORDER TRACKING FILTER ---
    platform_name = 'MercadoLivre'
    ids_pedidos = []
    
    if not filtered_data.empty:
        # 1. Prepare orders list for Tracker
        # We need to group by Order ID first
        orders_for_tracker = []
        unique_orders_ml = filtered_data['N.º de venda'].unique()
        
        for oid in unique_orders_ml:
            order_items_df = filtered_data[filtered_data['N.º de venda'] == oid]
            items_list = []
            for _, r in order_items_df.iterrows():
                items_list.append({
                    'sku_externo': str(r.get('SKU', '')),
                    'item_externo_id': str(r.get('SKU', '')), # ML doesn't have item ID in this report, use SKU
                    'quantidade': int(r.get('Unidades', 1))
                })
            
            orders_for_tracker.append({
                'pedido_externo_id': str(oid),
                'items': items_list
            })
            
        # 2. Filter Processed Items
        filtered_orders = order_tracker_service.filter_processed_items(orders_for_tracker, platform_name)
        
        # 3. Update DataFrame to keep ONLY valid orders/items
        valid_rows_refined = []
        for fo in filtered_orders:
            oid = fo['pedido_externo_id']
            # Find original rows for this order
            original_rows = filtered_data[filtered_data['N.º de venda'] == oid].to_dict('records')
            
            remaining_items = fo['items'] # These are the ones still needed
            
            # Simple approach: Rebuild DF from remaining_items + metadata from first original row
            if original_rows:
                meta = original_rows[0].copy() # Copy metadata like Title, Buyer, etc.
                for item in remaining_items:
                    row_data = meta.copy()
                    row_data['SKU'] = item['sku_externo']
                    row_data['Unidades'] = item['quantidade']
                    # Try to find original specific row for this SKU to get Variação/Title correct if mixed
                    matching_orig = next((orow for orow in original_rows if str(orow.get('SKU')) == item['sku_externo']), None)
                    if matching_orig:
                        row_data['Título do anúncio'] = matching_orig.get('Título do anúncio')
                        row_data['Variação'] = matching_orig.get('Variação')
                    
                    valid_rows_refined.append(row_data)

        if valid_rows_refined:
            filtered_data = pd.DataFrame(valid_rows_refined)
        else:
            filtered_data = pd.DataFrame(columns=filtered_data.columns)

    raw_data = filtered_data.copy()

    # Process Miolo
    filtered_data['Miolo'] = filtered_data['SKU'].apply(lambda x: resolve_miolo(x, 10))
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)
    filtered_data['Variação'] = filtered_data['Variação'].fillna('-')

    # Consolida capas
    if not filtered_data.empty:
        capas_data = filtered_data.groupby(CAPAS_GROUP['mercadolivre'])['Unidades'].sum(
        ).reset_index(name='Total').sort_values(['Total'], ascending=[False]).copy()
        total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

        # Consolida miolos
        miolos_data = filtered_data.groupby('Miolo')['Unidades'].sum().reset_index(
            name='Total').sort_values(['Total'], ascending=[False]).copy()
        total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

        # Order Miolos
        miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    # Capas x Miolos
        capas_miolos_data = filtered_data.groupby(['Título do anúncio', 'SKU', 'Variação', 'Miolo']).agg({
            'Unidades': 'sum',
            'N.º de venda': lambda x: list(x.astype(str))
        }).reset_index().rename(columns={'Unidades': 'Total', 'N.º de venda': 'order_refs'}).copy()
        
        capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip().str.upper()
        capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(miolo_order).astype('Int64')
        capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[True, False]).drop(columns=['Miolo_Ordem'])
        
        ids_pedidos = filtered_data['N.º de venda'].astype(str).unique().tolist()
    else:
        capas_data = pd.DataFrame()
        total_capas = 0
        miolos_data = pd.DataFrame()
        total_miolos = 0
        capas_miolos_data = pd.DataFrame(columns=['Título do anúncio', 'SKU', 'Variação', 'Miolo', 'Total'])
        ids_pedidos = []

    # --- UPDATED MAPPING LOGIC (Task 3 integration) ---
    capas_miolos_data['internal_product_id'] = None
    capas_miolos_data['internal_product_name'] = None
    capas_miolos_data['internal_product_sku'] = None
    capas_miolos_data['mapping_status'] = 'Não Mapeado'
    capas_miolos_data['potential_matches'] = None 
    capas_miolos_data['miolo_name'] = capas_miolos_data['Miolo'] # Populate fallback

    for index, row in capas_miolos_data.iterrows():
        external_name = row['Título do anúncio']
        external_sku = row['SKU']
        # Also pass variation info if available to help semantic match
        variation_name = row['Variação'] if row['Variação'] != '-' else None
        
        # Use the new resolve_variation method
        match = product_service.resolve_variation(
            sku_externo=external_sku,
            plataforma=platform_name,
            nome_externo=f"{external_name} - {variation_name}" if variation_name else external_name
        )

        if match:
            capas_miolos_data.loc[index, 'internal_product_id'] = match['id']
            capas_miolos_data.loc[index, 'internal_product_name'] = match['nome']
            capas_miolos_data.loc[index, 'internal_product_sku'] = match['sku']
            capas_miolos_data.loc[index, 'mapping_status'] = 'Mapeado'

            # --- ATUALIZAÇÃO DO MIOLO VIA BOM ---
            logging.info(f"[DEBUG MIOLO] Tentando associar miolo para produto: {match['nome']} (ID: {match['id']})")
            miolo_bom, id_produto_miolo = get_miolo_from_bom(match['id'])
            if miolo_bom:
                logging.info(f"[DEBUG MIOLO] Associado miolo via BOM: {miolo_bom} (ID: {id_produto_miolo})")
                capas_miolos_data.loc[index, 'Miolo'] = miolo_bom
                capas_miolos_data.loc[index, 'miolo_name'] = miolo_bom
                capas_miolos_data.loc[index, 'id_produto_miolo'] = id_produto_miolo
            else:
                logging.info(f"[DEBUG MIOLO] Nenhum miolo encontrado via BOM para produto {match['nome']} (ID: {match['id']})")
                # Fallback: tentar encontrar produto de miolo com base no nome extraído
                try:
                    # Obter o nome do miolo a partir do campo 'Miolo' do DataFrame
                    extracted_miolo = row['Miolo']
                    logging.info(f"[DEBUG MIOLO] Tentando fallback para miolo: {extracted_miolo}")

                    # Buscar produtos com nome contendo "Miolo " + extracted_miolo
                    from nistiprint_shared.database.supabase_db_service import supabase_db
                    response = supabase_db.table('produtos').select('*').ilike('nome', f'Miolo %{extracted_miolo}%').execute()

                    if response.data:
                        miolo_produto = response.data[0]  # Pegar o primeiro resultado
                        logging.info(f"[DEBUG MIOLO] Produto miolo encontrado via fallback: {miolo_produto['nome']} (ID: {miolo_produto['id']})")
                        capas_miolos_data.loc[index, 'miolo_name'] = miolo_produto['nome']
                        capas_miolos_data.loc[index, 'id_produto_miolo'] = miolo_produto['id']
                    else:
                        logging.info(f"[DEBUG MIOLO] Nenhum produto miolo encontrado via fallback para: {extracted_miolo}")

                except Exception as e:
                    logging.error(f"[DEBUG MIOLO] Erro no fallback de associação de miolo: {e}")
            # ------------------------------------
        else:
            # Fallback: Try fuzzy search to suggest matches (Legacy behavior preserved for UI)
            candidates = product_service.find_internal_product(platform_name, external_sku, external_name)
            if len(candidates) >= 1:
                capas_miolos_data.loc[index, 'mapping_status'] = 'Não Mapeado (Sugestões Disponíveis)'
                capas_miolos_data.loc[index, 'potential_matches'] = json.dumps([{'id': m['id'], 'name': m['nome'], 'sku': m['sku']} for m in candidates])

    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        # Note: bling_orders_data currently contains ALL orders found in file.
        # Ideally, we should filter this too, but for PDF generation (which is stateless),
        # it might be fine to print duplicates if user explicitly asked.
        # However, to be consistent, we filter based on valid_ids
        valid_ids_set = set(ids_pedidos)
        bling_orders_data = [o for o in bling_orders_data if str(o['numeroLoja']) in valid_ids_set]
        
        # Enriquecer com personalizações do Supabase
        bling_orders_data = enrich_orders_with_personalizations(bling_orders_data, platform_name, mode=options.get('mode'))

        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

    total_pedidos_plataforma = len(ids_pedidos)

    return capas_data, total_capas, miolos_data, total_miolos, capas_miolos_data, ids_pedidos_chunks, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, raw_data


def process_shopee(file, period_filter, options=None, bling_client=None):

    bling_orders_id = []
    bling_orders_data = []
    bling_orders_id_numero = []
    bling_orders_not_found = []
    buyer_data = [] 

    data = pd.read_excel(file)
    data['Data prevista de envio'] = pd.to_datetime(data['Data prevista de envio'], errors='coerce')

    is_flex = "Flex" in options.get('plataforma', '') or "flex" in str(options.get('channel_slug', '')).lower()

    base_condition = data['Opção de envio'].str.contains("Entrega Rápida") if is_flex else (
        data['Número de rastreamento'].isnull() & \
        ~data['Opção de envio'].str.contains("Estoque") & \
        ~data['Opção de envio'].str.contains("Full") & \
        ~data['Opção de envio'].str.contains("Entrega Rápida") 
        )

    filtered_data = apply_date_filter(data[base_condition], period_filter, 'Data prevista de envio')[COLUMNS['shopee']].copy()
    
    # Store Buyer Info logic (Kept as is)
    unique_orders = filtered_data[['ID do pedido', 'Status do pedido', 'Nome de usuário (comprador)', 'Observação do comprador']].drop_duplicates(subset=['ID do pedido'])
    from nistiprint_shared.database.supabase_db_service import get_db_session as get_supabase_session
    with get_supabase_session() as session:
        for _, row in unique_orders.iterrows():
            order_sn = str(row['ID do pedido'])
            status = row['Status do pedido']
            username = row['Nome de usuário (comprador)']
            message = row['Observação do comprador'] if pd.notna(row['Observação do comprador']) else ''
            buyer_info_json = json.dumps({"username": username})

            existing_orders = session.query_model(ShopeeOrders).filter_by(codigo_pedido=order_sn).all()

            if existing_orders:
                existing_order = existing_orders[0]
                existing_order.informacoes_comprador = buyer_info_json
                existing_order.mensagem = message
                existing_order.status_pedido = status
                existing_order.updated_at = datetime.utcnow()
                from nistiprint_shared.database.supabase_db_service import supabase_db
                update_data = {
                    'informacoes_comprador': buyer_info_json,
                    'mensagem': message,
                    'status_pedido': status,
                    'updated_at': datetime.utcnow().isoformat()
                }
                supabase_db.update('pedidos_shopee', existing_order.id, update_data)
            else:
                new_order = ShopeeOrders()
                new_order.codigo_pedido = order_sn
                new_order.informacoes_comprador = buyer_info_json
                new_order.mensagem = message
                new_order.status_pedido = status
                new_order.created_at = datetime.utcnow()
                new_order.updated_at = datetime.utcnow()
                from nistiprint_shared.database.supabase_db_service import supabase_db
                order_dict = {
                    'codigo_pedido': new_order.codigo_pedido,
                    'status_pedido': status,
                    'informacoes_comprador': new_order.informacoes_comprador,
                    'mensagem': new_order.mensagem,
                    'created_at': new_order.created_at.isoformat() if new_order.created_at else None,
                    'updated_at': new_order.updated_at.isoformat() if new_order.updated_at else None
                }
                supabase_db.insert('pedidos_shopee', order_dict)


    # --- ORDER TRACKING FILTER ---
    platform_name = 'Shopee'
    
    if not filtered_data.empty:
        orders_for_tracker = []
        unique_orders_shopee = filtered_data['ID do pedido'].unique()
        
        for oid in unique_orders_shopee:
            order_items_df = filtered_data[filtered_data['ID do pedido'] == oid]
            items_list = []
            for _, r in order_items_df.iterrows():
                # Handle both old and new field names for backward compatibility
                sku_value = str(r.get('Número de referência SKU', r.get('Nº de referência do SKU principal', '')))
                items_list.append({
                    'sku_externo': sku_value,
                    'item_externo_id': sku_value, # Shopee SKU reference
                    'quantidade': int(r.get('Quantidade', 1))
                })
            
            orders_for_tracker.append({
                'pedido_externo_id': str(oid),
                'items': items_list
            })
            
        filtered_orders = order_tracker_service.filter_processed_items(orders_for_tracker, platform_name)
        
        # Reconstruct DataFrame
        valid_rows_refined = []
        for fo in filtered_orders:
            oid = fo['pedido_externo_id']
            original_rows = filtered_data[filtered_data['ID do pedido'] == oid].to_dict('records')
            
            remaining_items = fo['items']
            if original_rows:
                meta = original_rows[0].copy()
                for item in remaining_items:
                    row_data = meta.copy()
                    # Update both old and new field names for compatibility
                    row_data['Nº de referência do SKU principal'] = item['sku_externo']
                    row_data['Número de referência SKU'] = item['sku_externo']
                    row_data['Quantidade'] = item['quantidade']

                    matching_orig = next((orow for orow in original_rows if str(orow.get('Número de referência SKU', orow.get('Nº de referência do SKU principal', ''))) == item['sku_externo']), None)
                    if matching_orig:
                        row_data['Nome do Produto'] = matching_orig.get('Nome do Produto')
                        row_data['Nome da variação'] = matching_orig.get('Nome da variação')
                    
                    valid_rows_refined.append(row_data)

        if valid_rows_refined:
            filtered_data = pd.DataFrame(valid_rows_refined)
        else:
            filtered_data = pd.DataFrame(columns=filtered_data.columns)


    # Process Miolo - check for new field name first, then fall back to old field name
    sku_column = 'Número de referência SKU' if 'Número de referência SKU' in filtered_data.columns else 'Nº de referência do SKU principal'
    filtered_data['Miolo'] = filtered_data[sku_column].apply(lambda x: resolve_miolo(x, 10))
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)
    filtered_data['Nome da variação'] = filtered_data['Nome da variação'].fillna('-')

    # Consolida capas
    capas_data = filtered_data.groupby(CAPAS_GROUP['shopee'])['Quantidade'].sum(
    ).reset_index(name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

    # Consolida miolos
    miolos_data = filtered_data.groupby('Miolo')['Quantidade'].sum().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

    miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    # Use appropriate column name based on what's available in the dataframe
    sku_column = 'Número de referência SKU' if 'Número de referência SKU' in filtered_data.columns else 'Nº de referência do SKU principal'
    capas_miolos_data = filtered_data.groupby(['Nome do Produto', sku_column, 'Nome da variação', 'Miolo']).agg({
        'Quantidade': 'sum',
        'ID do pedido': lambda x: list(x.astype(str))
    }).reset_index().rename(columns={'Quantidade': 'Total', 'ID do pedido': 'order_refs'}).copy()
    
    capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip().str.upper()
    capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(miolo_order).astype('Int64')
    capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[True, False]).drop(columns=['Miolo_Ordem'])

    # --- UPDATED MAPPING LOGIC ---
    capas_miolos_data['internal_product_id'] = None
    capas_miolos_data['internal_product_name'] = None
    capas_miolos_data['internal_product_sku'] = None
    capas_miolos_data['mapping_status'] = 'Não Mapeado'
    capas_miolos_data['potential_matches'] = None
    capas_miolos_data['miolo_name'] = capas_miolos_data['Miolo']
    capas_miolos_data['id_produto_miolo'] = None

    for index, row in capas_miolos_data.iterrows():
        external_name = row['Nome do Produto']
        external_sku = row.get('Número de referência SKU', row.get('Nº de referência do SKU principal', ''))
        variation_name = row['Nome da variação'] if row['Nome da variação'] != '-' else None

        # Log the mapping attempt
        import logging
        logging.info(f"Mapeamento tentativa - SKU externo: '{external_sku}', Nome externo: '{external_name}', Variação: '{variation_name}'")

        match = product_service.resolve_variation(
            sku_externo=external_sku,
            plataforma=platform_name,
            nome_externo=f"{external_name} - {variation_name}" if variation_name else external_name
        )

        if match:
            capas_miolos_data.loc[index, 'internal_product_id'] = match['id']
            capas_miolos_data.loc[index, 'internal_product_name'] = match['nome']
            capas_miolos_data.loc[index, 'internal_product_sku'] = match['sku']
            capas_miolos_data.loc[index, 'mapping_status'] = 'Mapeado'
            logging.info(f"Mapeamento bem sucedido - SKU externo: '{external_sku}' -> Produto interno ID: {match['id']}, Nome: '{match['nome']}', SKU: '{match['sku']}'")
            
            # --- ATUALIZAÇÃO DO MIOLO VIA BOM ---
            logging.info(f"[DEBUG MIOLO] Tentando associar miolo para produto: {match['nome']} (ID: {match['id']})")
            miolo_bom, id_produto_miolo = get_miolo_from_bom(match['id'])
            if miolo_bom:
                logging.info(f"[DEBUG MIOLO] Associado miolo via BOM: {miolo_bom} (ID: {id_produto_miolo})")
                capas_miolos_data.loc[index, 'Miolo'] = miolo_bom
                capas_miolos_data.loc[index, 'miolo_name'] = miolo_bom
                capas_miolos_data.loc[index, 'id_produto_miolo'] = id_produto_miolo
            else:
                logging.info(f"[DEBUG MIOLO] Nenhum miolo encontrado via BOM para produto {match['nome']} (ID: {match['id']})")
                # Fallback: tentar encontrar produto de miolo com base no nome extraído
                try:
                    # Obter o nome do miolo a partir do campo 'Miolo' do DataFrame
                    extracted_miolo = row['Miolo']
                    logging.info(f"[DEBUG MIOLO] Tentando fallback para miolo: {extracted_miolo}")

                    # Buscar produtos com nome contendo "Miolo " + extracted_miolo
                    from nistiprint_shared.database.supabase_db_service import supabase_db
                    response = supabase_db.table('produtos').select('*').ilike('nome', f'Miolo %{extracted_miolo}%').execute()

                    if response.data:
                        miolo_produto = response.data[0]  # Pegar o primeiro resultado
                        logging.info(f"[DEBUG MIOLO] Produto miolo encontrado via fallback: {miolo_produto['nome']} (ID: {miolo_produto['id']})")
                        capas_miolos_data.loc[index, 'miolo_name'] = miolo_produto['nome']
                        capas_miolos_data.loc[index, 'id_produto_miolo'] = miolo_produto['id']
                    else:
                        logging.info(f"[DEBUG MIOLO] Nenhum produto miolo encontrado via fallback para: {extracted_miolo}")

                except Exception as e:
                    logging.error(f"[DEBUG MIOLO] Erro no fallback de associação de miolo: {e}")
            # ------------------------------------
        else:
            logging.info(f"Mapeamento direto falhou para SKU externo: '{external_sku}', buscando candidatos...")
            candidates = product_service.find_internal_product(platform_name, external_sku, external_name)
            logging.info(f"Encontrados {len(candidates)} candidatos para SKU externo: '{external_sku}'")

            if len(candidates) >= 1:
                capas_miolos_data.loc[index, 'mapping_status'] = 'Não Mapeado (Sugestões Disponíveis)'
                potential_matches_data = [{'id': m['id'], 'name': m['nome'], 'sku': m['sku']} for m in candidates]
                capas_miolos_data.loc[index, 'potential_matches'] = json.dumps(potential_matches_data)
            else:
                logging.info(f"Nenhum candidato encontrado para SKU externo: '{external_sku}'")
    
    ids_pedidos = filtered_data['ID do pedido'].astype(str).unique().tolist()
    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found = bling_client.get_orders_by_store_numbers(ids_pedidos)

        # Enriquecer com personalizações do Supabase
        bling_orders_data = enrich_orders_with_personalizations(bling_orders_data, platform_name, mode=options.get('mode'))

        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], x['total_items'], len(x['itens']), len(
            [item for item in x['itens'] if item['custom_tag'] != '']), next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')))

    total_pedidos_plataforma = len(ids_pedidos)

    return capas_data, total_capas, miolos_data, total_miolos, capas_miolos_data, ids_pedidos_chunks, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, buyer_data


def process_amazon(file, period_filter, options=None, bling_client=None):

    bling_orders_id = []
    bling_orders_data = []
    bling_orders_id_numero = []
    bling_orders_not_found = []
    buyer_data = [] 

    data = pd.read_csv(file)
    data['Data prevista para envio'] = pd.to_datetime(data['Data prevista para envio'], errors='coerce')

    filtered_data = apply_date_filter(data, period_filter, 'Data prevista para envio')[COLUMNS['amazon']].copy()

    def resolve_amazon_miolo(row_sku):
        val = row_sku[:10] if row_sku else '-'
        val = apply_miolo_fixes(val)
        val = fix_sku_devocional_amazon(val)
        val = fix_amazon_25_to_26(val)
        return val

    filtered_data['Miolo'] = filtered_data['SKU'].apply(resolve_amazon_miolo)
    
    # Merge columns Shipment ID and Customer Order ID for uniqueness
    filtered_data['ID do pedido'] = filtered_data['ID da remessa'].astype(str) + "|" + filtered_data['ID do pedido do cliente'].astype(str)

    # --- ORDER TRACKING FILTER ---
    platform_name = 'Amazon'    
    if not filtered_data.empty:
        orders_for_tracker = []
        unique_orders_amazon = filtered_data['ID do pedido'].unique()
        
        for oid in unique_orders_amazon:
            order_items_df = filtered_data[filtered_data['ID do pedido'] == oid]
            items_list = []
            for _, r in order_items_df.iterrows():
                items_list.append({
                    'sku_externo': str(r.get('SKU', '')),
                    'item_externo_id': str(r.get('SKU', '')), 
                    'quantidade': int(r.get('Unidades', 1))
                })
            
            # Note: Using AmazonOrderId (ID do pedido do cliente) for tracking if available, 
            # but 'ID do pedido' here is a composite key.
            # Plan says: "Amazon -> ID do pedido do cliente".
            # So we should pass the real Amazon Order ID to the tracker.
            real_order_id = str(order_items_df.iloc[0]['ID do pedido do cliente'])
            
            orders_for_tracker.append({
                'pedido_externo_id': real_order_id,
                'items': items_list
            })
            
        filtered_orders = order_tracker_service.filter_processed_items(orders_for_tracker, platform_name)
        
        # Reconstruct DataFrame
        valid_rows_refined = []
        for fo in filtered_orders:
            real_oid = fo['pedido_externo_id']
            # We have to find rows where 'ID do pedido do cliente' matches
            original_rows = filtered_data[filtered_data['ID do pedido do cliente'].astype(str) == real_oid].to_dict('records')
            
            remaining_items = fo['items']
            if original_rows:
                meta = original_rows[0].copy()
                for item in remaining_items:
                    row_data = meta.copy()
                    row_data['SKU'] = item['sku_externo']
                    row_data['Unidades'] = item['quantidade']
                    # Amazon might have multiple lines for same order/sku but different shipments?
                    # The composite key logic suggests that.
                    # But for tracking production, we care about the item quantity.
                    
                    # Try to find best matching row to preserve shipment info
                    matching_orig = next((orow for orow in original_rows if str(orow.get('SKU')) == item['sku_externo']), None)
                    if matching_orig:
                        row_data['ID da remessa'] = matching_orig.get('ID da remessa')
                        row_data['ID do pedido'] = matching_orig.get('ID do pedido') # Restore composite key
                    
                    valid_rows_refined.append(row_data)

        if valid_rows_refined:
            filtered_data = pd.DataFrame(valid_rows_refined)
        else:
            filtered_data = pd.DataFrame(columns=filtered_data.columns)


    # Consolida capas
    capas_data = filtered_data.groupby(CAPAS_GROUP['amazon'])['Unidades'].sum(
    ).reset_index(name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

    # Consolida miolos
    miolos_data = filtered_data.groupby('Miolo')['Unidades'].sum().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

    miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    capas_miolos_data = filtered_data.groupby(['Título', 'SKU', 'Miolo']).agg({
        'Unidades': 'sum',
        'ID do pedido do cliente': lambda x: list(x.astype(str))
    }).reset_index().rename(columns={'Unidades': 'Total', 'ID do pedido do cliente': 'order_refs'}).copy()
    
    capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip().str.upper()
    capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(miolo_order).astype('Int64')
    capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[True, False]).drop(columns=['Miolo_Ordem'])

    # --- UPDATED MAPPING LOGIC ---
    capas_miolos_data['internal_product_id'] = None
    capas_miolos_data['internal_product_name'] = None
    capas_miolos_data['internal_product_sku'] = None
    capas_miolos_data['mapping_status'] = 'Não Mapeado'
    capas_miolos_data['potential_matches'] = None
    capas_miolos_data['miolo_name'] = capas_miolos_data['Miolo']
    capas_miolos_data['id_produto_miolo'] = None

    for index, row in capas_miolos_data.iterrows():
        external_name = row['Título']
        external_sku = row['SKU']
        
        match = product_service.resolve_variation(
            sku_externo=external_sku,
            plataforma=platform_name,
            nome_externo=external_name
        )

        if match:
            capas_miolos_data.loc[index, 'internal_product_id'] = match['id']
            capas_miolos_data.loc[index, 'internal_product_name'] = match['nome']
            capas_miolos_data.loc[index, 'internal_product_sku'] = match['sku']
            capas_miolos_data.loc[index, 'mapping_status'] = 'Mapeado'

            # --- ATUALIZAÇÃO DO MIOLO VIA BOM ---
            logging.info(f"[DEBUG MIOLO] Tentando associar miolo para produto: {match['nome']} (ID: {match['id']})")
            miolo_bom, id_produto_miolo = get_miolo_from_bom(match['id'])
            if miolo_bom:
                logging.info(f"[DEBUG MIOLO] Associado miolo via BOM: {miolo_bom} (ID: {id_produto_miolo})")
                capas_miolos_data.loc[index, 'Miolo'] = miolo_bom
                capas_miolos_data.loc[index, 'miolo_name'] = miolo_bom
                capas_miolos_data.loc[index, 'id_produto_miolo'] = id_produto_miolo
            else:
                logging.info(f"[DEBUG MIOLO] Nenhum miolo encontrado via BOM para produto {match['nome']} (ID: {match['id']})")
                # Fallback: tentar encontrar produto de miolo com base no nome extraído
                try:
                    # Obter o nome do miolo a partir do campo 'Miolo' do DataFrame
                    extracted_miolo = row['Miolo']
                    logging.info(f"[DEBUG MIOLO] Tentando fallback para miolo: {extracted_miolo}")

                    # Buscar produtos com nome contendo "Miolo " + extracted_miolo
                    from nistiprint_shared.database.supabase_db_service import supabase_db
                    response = supabase_db.table('produtos').select('*').ilike('nome', f'Miolo %{extracted_miolo}%').execute()

                    if response.data:
                        miolo_produto = response.data[0]  # Pegar o primeiro resultado
                        logging.info(f"[DEBUG MIOLO] Produto miolo encontrado via fallback: {miolo_produto['nome']} (ID: {miolo_produto['id']})")
                        capas_miolos_data.loc[index, 'miolo_name'] = miolo_produto['nome']
                        capas_miolos_data.loc[index, 'id_produto_miolo'] = miolo_produto['id']
                    else:
                        logging.info(f"[DEBUG MIOLO] Nenhum produto miolo encontrado via fallback para: {extracted_miolo}")

                except Exception as e:
                    logging.error(f"[DEBUG MIOLO] Erro no fallback de associação de miolo: {e}")
            # ------------------------------------
        else:
            candidates = product_service.find_internal_product(platform_name, external_sku, external_name)
            if len(candidates) >= 1:
                capas_miolos_data.loc[index, 'mapping_status'] = 'Não Mapeado (Sugestões Disponíveis)'
                capas_miolos_data.loc[index, 'potential_matches'] = json.dumps([{'id': m['id'], 'name': m['nome'], 'sku': m['sku']} for m in candidates])

    ids_pedidos = filtered_data['ID do pedido'].astype(str).unique().tolist()
    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found = bling_client.get_orders_by_store_numbers(ids_pedidos)

        # Enriquecer com personalizações do Supabase
        bling_orders_data = enrich_orders_with_personalizations(bling_orders_data, platform_name, mode=options.get('mode'))

        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], x['total_items'], len(x['itens']), len(
            [item for item in x['itens'] if item['custom_tag'] != '']), next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')))

    total_pedidos_plataforma = len(ids_pedidos)

    return capas_data, total_capas, miolos_data, total_miolos, capas_miolos_data, ids_pedidos_chunks, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, buyer_data


def process_shein(file, period_filter, options=None, bling_client=None):

    bling_orders_id = []
    bling_orders_data = []
    bling_orders_id_numero = []
    bling_orders_not_found = []
    buyer_data = []

    data = pd.read_excel(file, skiprows=1)

    base_condition = data['Código de rastreio'].isnull()
    for column in COLUMN_SHIP_DATE['shein']:
        if column in data.columns:
            data.rename(columns={column: 'Prazo final de impressão de etiqueta'}, inplace=True)
            break

    data['Prazo final de impressão de etiqueta'].fillna(data['Data e hora requeridas para coleta'], inplace=True)
    data['Prazo final de impressão de etiqueta'] = data['Prazo final de impressão de etiqueta'].apply(replace_month)
    data['Prazo final de impressão de etiqueta'] = pd.to_datetime(data['Prazo final de impressão de etiqueta'], errors='coerce')

    filtered_data = apply_date_filter(data[base_condition], period_filter, 'Prazo final de impressão de etiqueta')[COLUMNS['shein']].copy()

    # Process Miolo
    filtered_data['Miolo'] = filtered_data['SKU do vendedor'].apply(lambda x: resolve_miolo(x, 10))
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)

    # --- ORDER TRACKING FILTER ---
    platform_name = 'Shein'
    
    if not filtered_data.empty:
        orders_for_tracker = []
        unique_orders_shein = filtered_data['Número do pedido'].unique()
        
        for oid in unique_orders_shein:
            order_items_df = filtered_data[filtered_data['Número do pedido'] == oid]
            items_list = []
            for _, r in order_items_df.iterrows():
                items_list.append({
                    'sku_externo': str(r.get('SKU do vendedor', '')),
                    'item_externo_id': str(r.get('SKU do vendedor', '')),
                    'quantidade': 1
                })
            
            orders_for_tracker.append({
                'pedido_externo_id': str(oid),
                'items': items_list
            })
            
        filtered_orders = order_tracker_service.filter_processed_items(orders_for_tracker, platform_name)
        
        # Reconstruct DataFrame
        valid_rows_refined = []
        for fo in filtered_orders:
            oid = fo['pedido_externo_id']
            original_rows = filtered_data[filtered_data['Número do pedido'] == oid].to_dict('records')
            
            remaining_items = fo['items']
            if original_rows:
                meta = original_rows[0].copy()
                for item in remaining_items:
                    row_data = meta.copy()
                    row_data['SKU do vendedor'] = item['sku_externo']
                    # Shein qty is mostly 1 per line, but if we need to set it, we assume 1 or handle duplicates.
                    # Since Tracker returns list of items, we add a row for each.
                    valid_rows_refined.append(row_data)

        if valid_rows_refined:
            filtered_data = pd.DataFrame(valid_rows_refined)
        else:
            filtered_data = pd.DataFrame(columns=filtered_data.columns)

    # Consolida capas
    capas_data = filtered_data.groupby(CAPAS_GROUP['shein']).size().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

    # Consolida miolos
    miolos_data = filtered_data.groupby('Miolo').size().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

    miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    capas_miolos_data = filtered_data.groupby(['Nome do produto', 'SKU do vendedor', 'Miolo']).agg({
        'Número do pedido': lambda x: list(x.astype(str))
    }).reset_index().rename(columns={'Número do pedido': 'order_refs'}).copy()
    capas_miolos_data['Total'] = capas_miolos_data['order_refs'].apply(len)
    
    capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip().str.upper()
    capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(miolo_order).astype('Int64')
    capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[True, False]).drop(columns=['Miolo_Ordem'])

    # --- UPDATED MAPPING LOGIC ---
    capas_miolos_data['internal_product_id'] = None
    capas_miolos_data['internal_product_name'] = None
    capas_miolos_data['internal_product_sku'] = None
    capas_miolos_data['mapping_status'] = 'Não Mapeado'
    capas_miolos_data['potential_matches'] = None
    capas_miolos_data['miolo_name'] = capas_miolos_data['Miolo']
    capas_miolos_data['id_produto_miolo'] = None

    for index, row in capas_miolos_data.iterrows():
        external_name = row['Nome do produto']
        external_sku = row['SKU do vendedor']
        
        match = product_service.resolve_variation(
            sku_externo=external_sku,
            plataforma=platform_name,
            nome_externo=external_name
        )

        if match:
            capas_miolos_data.loc[index, 'internal_product_id'] = match['id']
            capas_miolos_data.loc[index, 'internal_product_name'] = match['nome']
            capas_miolos_data.loc[index, 'internal_product_sku'] = match['sku']
            capas_miolos_data.loc[index, 'mapping_status'] = 'Mapeado'

            # --- ATUALIZAÇÃO DO MIOLO VIA BOM ---
            logging.info(f"[DEBUG MIOLO] Tentando associar miolo para produto: {match['nome']} (ID: {match['id']})")
            miolo_bom, id_produto_miolo = get_miolo_from_bom(match['id'])
            if miolo_bom:
                logging.info(f"[DEBUG MIOLO] Associado miolo via BOM: {miolo_bom} (ID: {id_produto_miolo})")
                capas_miolos_data.loc[index, 'Miolo'] = miolo_bom
                capas_miolos_data.loc[index, 'miolo_name'] = miolo_bom
                capas_miolos_data.loc[index, 'id_produto_miolo'] = id_produto_miolo
            else:
                logging.info(f"[DEBUG MIOLO] Nenhum miolo encontrado via BOM para produto {match['nome']} (ID: {match['id']})")
                # Fallback: tentar encontrar produto de miolo com base no nome extraído
                try:
                    # Obter o nome do miolo a partir do campo 'Miolo' do DataFrame
                    extracted_miolo = row['Miolo']
                    logging.info(f"[DEBUG MIOLO] Tentando fallback para miolo: {extracted_miolo}")

                    # Buscar produtos com nome contendo "Miolo " + extracted_miolo
                    from nistiprint_shared.database.supabase_db_service import supabase_db
                    response = supabase_db.table('produtos').select('*').ilike('nome', f'Miolo %{extracted_miolo}%').execute()

                    if response.data:
                        miolo_produto = response.data[0]  # Pegar o primeiro resultado
                        logging.info(f"[DEBUG MIOLO] Produto miolo encontrado via fallback: {miolo_produto['nome']} (ID: {miolo_produto['id']})")
                        capas_miolos_data.loc[index, 'miolo_name'] = miolo_produto['nome']
                        capas_miolos_data.loc[index, 'id_produto_miolo'] = miolo_produto['id']
                    else:
                        logging.info(f"[DEBUG MIOLO] Nenhum produto miolo encontrado via fallback para: {extracted_miolo}")

                except Exception as e:
                    logging.error(f"[DEBUG MIOLO] Erro no fallback de associação de miolo: {e}")
            # ------------------------------------
        else:
            candidates = product_service.find_internal_product(platform_name, external_sku, external_name)
            if len(candidates) >= 1:
                capas_miolos_data.loc[index, 'mapping_status'] = 'Não Mapeado (Sugestões Disponíveis)'
                capas_miolos_data.loc[index, 'potential_matches'] = json.dumps([{'id': m['id'], 'name': m['nome'], 'sku': m['sku']} for m in candidates])

    ids_pedidos = filtered_data['Número do pedido'].astype(str).unique().tolist()
    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found = bling_client.get_orders_by_store_numbers(ids_pedidos)

        # Enriquecer com personalizações do Supabase
        bling_orders_data = enrich_orders_with_personalizations(bling_orders_data, platform_name, mode=options.get('mode'))

        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], x['total_items'], len(x['itens']), len(
            [item for item in x['itens'] if item['custom_tag'] != '']), next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')))

    total_pedidos_plataforma = len(ids_pedidos)

    return capas_data, total_capas, miolos_data, total_miolos, capas_miolos_data, ids_pedidos_chunks, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, buyer_data


def replace_month(date_str):
    from ..constants import MONTH_MAP
    for pt_month, en_month in MONTH_MAP.items():
        date_str = date_str.replace(pt_month, en_month)
    return date_str

