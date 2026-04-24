import pandas as pd
import json
from datetime import datetime
from utils import apply_date_filter, apply_miolo_fixes, fix_sku_devocional_amazon, generate_ids_chunks, prepare_ml_file, process_string, fix_amazon_25_to_26
from constants import COLUMNS, COLUMN_SHIP_DATE, CAPAS_GROUP
from services.database.database import db
from models.shopee_orders import ShopeeOrders
from services.ai_personalization_service import get_personalizations_by_bling_orders

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
        
        log_prefix = f"[ML DEBUG] Pkg ID: {rows[0].get('N.º de venda', 'N/A')} | Rows: {len(rows)} |"
        
        if is_valid:
            print(f"{log_prefix} STATUS: VALID (Found State: {valid_state_found})")
            count_packages_valid += 1
            
            # 1. Add to DataFrame list (for stats)
            # We add all rows that have an SKU, as they represent items
            for r in rows:
                sku = r.get('SKU')
                if not pd.isna(sku) and str(sku).strip() != '':
                    valid_rows_for_df.append(r)
            
            # 2. Build Bling Order (for PDF)
            header = rows[0]
            order_id = str(header.get('N.º de venda', ''))
            address = header.get('Endereço', '')
            total_pacote = header.get('Receita por produtos (BRL)')
            total_brl = header.get('Total (BRL)')
            
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
                        "valor": 0, # Items in package usually don't have individual price in this view
                        "variacao": row.get('Variação') if not row.get('Variação') == '' else None,
                        "custom_tag": "",
                        "original_id": str(r.get('N.º de venda', ''))
                    }
                     package_order['itens'].append(item)
            
            bling_orders_data.append(package_order)
            bling_orders_id_numero[order_id] = order_id
            
        else:
            print(f"{log_prefix} STATUS: INVALID (No valid state found)")


    for i, row in enumerate(records):
        state = str(row.get('Estado', ''))
        total_brl = row.get('Total (BRL)')
        is_total_empty = pd.isna(total_brl) or str(total_brl).strip() == ''

        is_package_header = state.startswith('Pacote de')
        
        # Logic to identify if this row belongs to the current package
        # It belongs if we have a current package AND (it's an item with empty total OR it's a header - wait, header starts new)
        # Actually:
        # If Header -> Start new package (process old if exists)
        # If Empty Total -> Add to current package
        # If Single Order (Not Header, Not Empty Total) -> Process old package, then process single
        
        log_row_info = f"Row {i} | ID: {row.get('N.º de venda', '')} | St: {state} | Tot: {total_brl}"

        if is_package_header:
            # New Package Started
            if current_package_rows:
                process_buffered_package(current_package_rows)
            current_package_rows = [row]
            print(f"[ML DEBUG] {log_row_info} -> ACTION: START NEW PACKAGE")
            
        elif current_package_rows and is_total_empty:
            # Continuation of current package
            current_package_rows.append(row)
            # print(f"[ML DEBUG] {log_row_info} -> ACTION: ADD TO PACKAGE") 
            
        else:
            # Not a package header, and not a package item (Total not empty)
            # Must be a single order or unrelated row
            
            # First, flush any pending package
            if current_package_rows:
                process_buffered_package(current_package_rows)
                current_package_rows = []
            
            # Now check if this is a valid single order
            if state in valid_states:
                print(f"[ML DEBUG] {log_row_info} -> ACTION: VALID SINGLE ORDER")
                count_single_valid += 1
                
                # 1. Add to DataFrame list
                valid_rows_for_df.append(row)
                
                # 2. Build Bling Order
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
                    "variacao": row.get('Variação') if not row.get('Variação') == '' else None,
                    "custom_tag": "",
                    "original_id": str(row.get('N.º de venda', ''))
                }
                order['itens'].append(item)
                bling_orders_data.append(order)
                bling_orders_id_numero[order_id] = order_id
            else:
                 pass
                 # print(f"[ML DEBUG] {log_row_info} -> ACTION: IGNORED/INVALID STATE")

    # Flush last package if exists
    if current_package_rows:
        process_buffered_package(current_package_rows)

    print(f"[ML DEBUG] SUMMARY: Pkgs Processed: {count_packages_processed}, Pkgs Valid: {count_packages_valid}, Singles Valid: {count_single_valid}")
    print(f"[ML DEBUG] Total Orders (Bling Data): {len(bling_orders_data)}")
    print(f"[ML DEBUG] Total Rows for Stats: {len(valid_rows_for_df)}")

    # Create Filtered Data from the collected valid rows
    if valid_rows_for_df:
        filtered_data = pd.DataFrame(valid_rows_for_df)
    else:
        filtered_data = pd.DataFrame(columns=data.columns) # Empty with same columns
    
    # Keep only necessary columns for stats
    # We need to ensure columns exist (if valid_rows_for_df was empty, we handled it)
    # But if valid_rows_for_df has data, it has all columns from original df
    if not filtered_data.empty:
        filtered_data = filtered_data[COLUMNS['mercadolivre']].copy()
        filtered_data['N.º de venda'] = filtered_data['N.º de venda'].astype(str)
    
    raw_data = filtered_data.copy() # Actually raw_data in previous logic was "filtered_data before column selection" but here we reconstruct
    # Note: In previous code, raw_data was the FULL filtered DF. Here valid_rows_for_df contains the dicts.
    # Let's recreate raw_data for return
    if valid_rows_for_df:
         raw_data = pd.DataFrame(valid_rows_for_df)
    else:
         raw_data = pd.DataFrame(columns=data.columns)

    # Process Miolo
    if not filtered_data.empty:
        filtered_data['Miolo'] = filtered_data['SKU'].str[:10]
        filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)
        filtered_data['Variação'] = filtered_data['Variação'].fillna('-')
    else:
        filtered_data['Miolo'] = []
        filtered_data['Variação'] = []

    # Consolida capas
    if not filtered_data.empty:
        capas_data = filtered_data.groupby(CAPAS_GROUP['mercadolivre'])['Unidades'].sum(
        ).reset_index(name='Total').sort_values(['Total'], ascending=[False]).copy()
        total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

        # Consolida miolos
        miolos_data = filtered_data.groupby('Miolo')['Unidades'].sum().reset_index(
            name='Total').sort_values(['Total'], ascending=[False]).copy()
        total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

        # Criar um dicionário para mapear a ordem dos valores de "Miolo" em miolos_data
        miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

        # Adicionar uma coluna auxiliar com a ordem correspondente
        capas_miolos_data = filtered_data.groupby(['Título do anúncio', 'SKU', 'Variação', 'Miolo'])['Unidades'].sum(
        ).reset_index(name='Total').copy()
        capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip(
        ).str.upper()
        capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(
            miolo_order).astype('Int64')
        # order capas_miolos_data by Miolo_Ordem descending
        capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[
            True, False]).drop(columns=['Miolo_Ordem'])
        
        ids_pedidos = filtered_data['N.º de venda'].astype(str).unique().tolist()
    else:
        capas_data = pd.DataFrame()
        total_capas = 0
        miolos_data = pd.DataFrame()
        total_miolos = 0
        capas_miolos_data = pd.DataFrame()
        ids_pedidos = []

    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        # This was already built during the loop above: bling_orders_data
        
        # Aplicar processamento adicional como no código original
        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        # Ordenar por critérios específicos || desabilitado para permitir que a ordem dos papéis de pedido seja idêntica à da impressão de etiqueta.
        # bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], x['total_items'], len(x['itens']), len(
        #     [item for item in x['itens'] if item['custom_tag'] != '']), next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')))

    total_pedidos_plataforma = len(ids_pedidos)

    return capas_data, total_capas, miolos_data, total_miolos, capas_miolos_data, ids_pedidos_chunks, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, raw_data 


def process_shopee(file, period_filter, options=None, bling_client=None):
    bling_orders_id = []
    bling_orders_data = []
    bling_orders_id_numero = []
    bling_orders_not_found = []
    buyer_data = []

    data = pd.read_excel(file)
    data['Data prevista de envio'] = pd.to_datetime(
        data['Data prevista de envio'], errors='coerce')

    base_condition = data['Opção de envio'].str.contains("Entrega Rápida") if "Flex" in options['platform'] else (
        data['Número de rastreamento'].isnull() & \
        ~data['Opção de envio'].str.contains("Estoque") & \
        ~data['Opção de envio'].str.contains("Full") & \
        ~data['Opção de envio'].str.contains("Entrega Rápida") \
        )

    filtered_data = apply_date_filter(
        data[base_condition], period_filter, 'Data prevista de envio')[COLUMNS['shopee']].copy()
    
    unique_orders = filtered_data[['ID do pedido', 'Nome de usuário (comprador)', 'Observação do comprador']].drop_duplicates(subset=['ID do pedido'])
    for _, row in unique_orders.iterrows():
        order_sn = str(row['ID do pedido'])
        username = row['Nome de usuário (comprador)']
        message = row['Observação do comprador'] if pd.notna(row['Observação do comprador']) else ''
        buyer_info_json = json.dumps({"username": username})
        
        # Check if order exists
        existing_order = ShopeeOrders.query.filter(
            (ShopeeOrders.order_sn == order_sn)
        ).first()
        
        if existing_order:
            # Update existing order
            existing_order.buyer_info = buyer_info_json
            existing_order.message = message
            existing_order.updated_at = datetime.utcnow()
        else:
            # Create new order
            order_id_int = None
            
            new_order = ShopeeOrders(
                order_sn=order_sn,
                buyer_info=buyer_info_json,
                message=message,
                order_id=order_id_int,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(new_order)
    
    if unique_orders.shape[0] > 0:
        db.session.commit()


    # Process Miolo
    filtered_data['Miolo'] = filtered_data['Número de referência SKU'].str[:10].fillna('-')
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)
    filtered_data['Nome da variação'] = filtered_data['Nome da variação'].fillna(
        '-')

    # Consolida capas
    capas_data = filtered_data.groupby(CAPAS_GROUP['shopee'])['Quantidade'].sum(
    ).reset_index(name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

    # Consolida miolos
    miolos_data = filtered_data.groupby('Miolo')['Quantidade'].sum().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

    # Criar um dicionário para mapear a ordem dos valores de "Miolo" em miolos_data
    miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    # Adicionar uma coluna auxiliar com a ordem correspondente
    capas_miolos_data = filtered_data.groupby(['Nome do Produto', 'Número de referência SKU', 'Nome da variação', 'Miolo'])['Quantidade'].sum(
    ).reset_index(name='Total').copy()
    capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip(
    ).str.upper()
    capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(
        miolo_order).astype('Int64')
    # order capas_miolos_data by Miolo_Ordem descending
    capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[
        True, False]).drop(columns=['Miolo_Ordem'])

    ids_pedidos = filtered_data['ID do pedido'].astype(
        str).unique().tolist()
    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found = bling_client.get_orders_by_store_numbers(ids_pedidos)

        # Importar modelos necessários para busca local
        from models.bling_pedidos import BlingPedidos
        from models.bling_pedido_itens import BlingPedidoItens
        from models.order_personalizations import OrderPersonalizations

        # Aplicar processamento adicional como no código original
        for order in bling_orders_data:
            store_number = order.get('numeroLoja')
            bling_number = order.get('numero')
            
            # Tentar buscar personalizações via banco de dados local primeiro (associação por ID)
            local_order = BlingPedidos.query.filter_by(numeroLoja=store_number, deletado=0).first()
            
            if local_order:
                # Buscar itens locais para ter a ponte entre SKU e Personalização
                local_items = BlingPedidoItens.query.filter_by(pedido_id=local_order.id).all()
                order_personalizations = OrderPersonalizations.query.filter_by(order_id=str(local_order.id)).all()
                
                order['hasCustomItem'] = 0
                for item in order['itens']:
                    item['personalizations'] = []
                    item_code = item.get('codigo')
                    item_description = item.get('descricao')
                    
                    for p in order_personalizations:
                        # Encontrar o item local ao qual esta personalização pertence
                        l_item = next((li for li in local_items if str(li.id) == p.item_id), None)
                        
                        is_match = False
                        if l_item:
                            # Se temos o item local, comparamos com o item da API (Bling)
                            # Prioridade para SKU, que resolve o problema de 2025 vs 2026
                            if l_item.codigo and l_item.codigo == item_code:
                                is_match = True
                            elif l_item.descricao == item_description or l_item.descricao in item_description or item_description in l_item.descricao:
                                is_match = True
                        
                        if is_match:
                            item['personalizations'].append({
                                'item_id': p.item_id,
                                'item_description': p.item_description,
                                'customization_name': p.customization_name,
                                'customization_initial': p.customization_initial,
                                'quantity_to_personalize': p.quantity_to_personalize,
                                'status': p.status
                            })
                    
                    if item['personalizations']:
                        order['hasCustomItem'] = 1
            else:
                # Fallback: Lógica original baseada em descrição caso o pedido não esteja no banco local
                order_personalizations_fallback = get_personalizations_by_bling_orders([bling_number]).get(bling_number, [])

                order['hasCustomItem'] = 0
                for item in order['itens']:
                    item['personalizations'] = []
                    item_code = item.get('codigo')
                    item_description = item.get('descricao')

                    for p in order_personalizations_fallback:
                        if (p['item_id'] == item_code or
                            p['item_description'] == item_description or
                            p['item_description'] in item_description or
                            item_description in p['item_description']):
                            item['personalizations'].append(p)

                    if item['personalizations']:
                        order['hasCustomItem'] = 1

            # Processamento comum (custom_tag e total_items)
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        # Ordenar por critérios específicos
        bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], len(x['itens']), min((item['descricao'] for item in x['itens']), default='') if x['itens'] else ''))

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

    filtered_data = apply_date_filter(data, period_filter, 'Data prevista para envio')[
        COLUMNS['amazon']].copy()

    # Process Miolo
    filtered_data['Miolo'] = filtered_data['SKU'].str[:10]
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(
        fix_sku_devocional_amazon)
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(fix_amazon_25_to_26)
    

    # Consolida capas
    capas_data = filtered_data.groupby(CAPAS_GROUP['amazon'])['Unidades'].sum(
    ).reset_index(name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

    # Consolida miolos
    miolos_data = filtered_data.groupby('Miolo')['Unidades'].sum().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

    # Criar um dicionário para mapear a ordem dos valores de "Miolo" em miolos_data
    miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    # Adicionar uma coluna auxiliar com a ordem correspondente
    capas_miolos_data = filtered_data.groupby(['Título', 'SKU', 'Miolo'])['Unidades'].sum(
    ).reset_index(name='Total').copy()
    capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip(
    ).str.upper()
    capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(
        miolo_order).astype('Int64')

    # order capas_miolos_data by Miolo_Ordem descending
    capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[
        True, False]).drop(columns=['Miolo_Ordem'])

    # merge columns Shipment ID and Customer Order ID
    filtered_data['ID do pedido'] = filtered_data['ID da remessa'].astype(str) + "|" + \
        filtered_data['ID do pedido do cliente'].astype(str)
    ids_pedidos = filtered_data['ID do pedido'].astype(
        str).unique().tolist()
    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found = bling_client.get_orders_by_store_numbers(ids_pedidos)

        # Aplicar processamento adicional como no código original
        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        # Ordenar por critérios específicos
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
    # Handle date column
    for column in COLUMN_SHIP_DATE['shein']:
        if column in data.columns:
            data.rename(
                columns={column: 'Prazo final de impressão de etiqueta'}, inplace=True)
            break

    data['Prazo final de impressão de etiqueta'].fillna(data['Data e hora requeridas para coleta'], inplace=True)
    data['Prazo final de impressão de etiqueta'] = data['Prazo final de impressão de etiqueta'].apply(
        replace_month)
    data['Prazo final de impressão de etiqueta'] = pd.to_datetime(
        data['Prazo final de impressão de etiqueta'], errors='coerce')

    filtered_data = apply_date_filter(
        data[base_condition], period_filter, 'Prazo final de impressão de etiqueta')[COLUMNS['shein']].copy()

    # Process Miolo
    filtered_data['Miolo'] = filtered_data['SKU do vendedor'].str[:10]
    filtered_data['Miolo'] = filtered_data['Miolo'].apply(apply_miolo_fixes)

    # Consolida capas
    capas_data = filtered_data.groupby(CAPAS_GROUP['shein']).size().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_capas = capas_data.sum(numeric_only=True).astype('int64').item()

    # Consolida miolos
    miolos_data = filtered_data.groupby('Miolo').size().reset_index(
        name='Total').sort_values(['Total'], ascending=[False]).copy()
    total_miolos = miolos_data.sum(numeric_only=True).astype('int64').item()

    # Criar um dicionário para mapear a ordem dos valores de "Miolo" em miolos_data
    miolo_order = {miolo: i for i, miolo in enumerate(miolos_data["Miolo"])}

    # Adicionar uma coluna auxiliar com a ordem correspondente
    capas_miolos_data = filtered_data.groupby(['Nome do produto', 'SKU do vendedor', 'Miolo']).size(
    ).reset_index(name='Total').copy()
    capas_miolos_data["Miolo"] = capas_miolos_data["Miolo"].str.strip(
    ).str.upper()
    capas_miolos_data["Miolo_Ordem"] = capas_miolos_data["Miolo"].map(
        miolo_order).astype('Int64')

    # order capas_miolos_data by Miolo_Ordem descending
    capas_miolos_data = capas_miolos_data.sort_values(['Miolo_Ordem', 'Total'], ascending=[
        True, False]).drop(columns=['Miolo_Ordem'])

    ids_pedidos = filtered_data['Número do pedido'].astype(
        str).unique().tolist()
    ids_pedidos_chunks = generate_ids_chunks(ids_pedidos)

    if options['print_orders']:
        bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found = bling_client.get_orders_by_store_numbers(ids_pedidos)

        # Aplicar processamento adicional como no código original
        for order in bling_orders_data:
            order['hasCustomItem'] = 0
            order['total_items'] = sum(item['quantidade'] for item in order['itens'])
            for item in order['itens']:
                custom_tag = process_string(item)
                if custom_tag != '':
                    order['hasCustomItem'] = 1
                item['custom_tag'] = custom_tag

        # Ordenar por critérios específicos
        bling_orders_data.sort(key=lambda x: (x['hasCustomItem'], x['total_items'], len(x['itens']), len(
            [item for item in x['itens'] if item['custom_tag'] != '']), next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')))

    total_pedidos_plataforma = len(ids_pedidos)

    return capas_data, total_capas, miolos_data, total_miolos, capas_miolos_data, ids_pedidos_chunks, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, buyer_data


def replace_month(date_str):
    from constants import MONTH_MAP
    for pt_month, en_month in MONTH_MAP.items():
        date_str = date_str.replace(pt_month, en_month)
    return date_str
