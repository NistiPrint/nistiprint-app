<?php

/**
 * update_orders.php
 * 
 * This script fetches orders from Bling API and stores them in the new database structure.
 * It's based on atualizar_pedidos.php but uses the new bling_pedidos and bling_pedido_itens tables.
 */

ini_set("max_execution_time", 2400);
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
ini_set('default_socket_timeout', 600);
error_reporting(E_ALL);
header("content-type: text/plain; charset=utf-8");
date_default_timezone_set('America/Sao_Paulo');

require 'vendor/autoload.php';

use Google\Cloud\Firestore\FirestoreClient;
use Google\Cloud\Firestore\Timestamp;

// --- Load Configuration ---
$appconfigPath = '/home/nistipri/appconfig/appconfig.php';
$firestoreCredPath = '/home/nistipri/appconfig/firebase_credentials.json';

// --- Configuração do Log (fora da função) ---
$logDir = __DIR__ . '/logs';
if (!is_dir($logDir)) {
    mkdir($logDir, 0755, true);
}

// Um arquivo por dia
$logFile = $logDir . '/' . date('Y-m-d') . '.log';

// --- Logging Setup ---
function logOrderUpdate($message) {
    global $logFile;
    
    $timestamp = date('Y-m-d H:i:s');
    $formattedMessage = "[{$timestamp}] {$message}\n";
    
    // Garante que múltiplas chamadas simultâneas não corrompam o arquivo
    @file_put_contents($logFile, $formattedMessage, FILE_APPEND | LOCK_EX);
    
    // Opcional: exibir no console/terminal
    echo $formattedMessage;
}

// --- Bling Configuration ---
$bling_antiga = [
    'open_status' => 15,
    'shopee_store_id_bling' => 204047801,
    'id_custom_column_bling' => 2797770
];

$bling_nova = [
    'open_status' => 15,
    'shopee_store_id_bling' => 205218967,
    'id_custom_column_bling' => 2797770
];

// --- Script Parameters ---
$data_inicial = date('Y-m-d', strtotime('-5 days'));
$data_final = date('Y-m-d');
$api_throttle_delay = 0.4; // Seconds

// --- Database Connection ---
function db_connection() {
    global $appconfigPath, $supabase_url, $supabase_key;
    try {
        if (!file_exists($appconfigPath)) {
            throw new Exception("Arquivo de configuração não encontrado.");
        }
        $appconfig = require $appconfigPath;
        
        // Load Supabase Config
        $supabase_url = $appconfig['supabase_url'] ?? null;
        $supabase_key = $appconfig['supabase_key'] ?? $appconfig['supabase_service_key'] ?? null;

    } catch (Exception $e) {
        $appconfig = require __DIR__ . '/appconfig.php';
    }
    
    $db_host = $appconfig['db_host'];
    $db_name = $appconfig['db_name'];
    $db_user = $appconfig['db_user'];
    $db_pass = $appconfig['db_pass'];
    
    try {
        $dbh = new PDO("mysql:host={$db_host};dbname={$db_name};charset=utf8", $db_user, $db_pass);
        $dbh->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $dbh->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        logOrderUpdate("Conexão com o banco de dados estabelecida com sucesso.");
        return $dbh;
    } catch (PDOException $e) {
        $error = "Erro na conexão com o banco de dados: " . $e->getMessage();
        logOrderUpdate($error);
        die($error);
    }
}

/**
 * Synchronizes data to Supabase using its REST API.
 */
function syncToSupabase(string $table, string $method, array $data, ?string $queryParams = null): array
{
    global $supabase_url, $supabase_key;

    if (empty($supabase_url) || empty($supabase_key)) {
        return ['success' => false, 'error' => 'Supabase credentials not configured'];
    }

    $url = rtrim($supabase_url, '/') . '/rest/v1/' . $table;
    if ($queryParams) {
        $url .= '?' . $queryParams;
    }

    $ch = curl_init($url);
    $payload = json_encode($data);

    $headers = [
        'apikey: ' . $supabase_key,
        'Authorization: Bearer ' . $supabase_key,
        'Content-Type: application/json',
        'Prefer: return=minimal'
    ];

    if ($method === 'POST' && strpos($queryParams ?? '', 'on_conflict') !== false) {
        $headers[] = 'Prefer: resolution=merge-duplicates';
    }

    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
    curl_setopt($ch, CURLOPT_TIMEOUT, 10);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curlError = curl_error($ch);
    curl_close($ch);

    $success = ($httpCode >= 200 && $httpCode < 300);

    if (!$success) {
        logOrderUpdate("SUPABASE_ERROR [{$table}]: HTTP {$httpCode} - " . ($curlError ?: $response));
    }

    return [
        'success' => $success,
        'status' => $httpCode,
        'response' => $response,
        'error' => $curlError
    ];
}

$dbh = db_connection();

// --- Fetch Settings & Refresh Tokens ---
try {
    $bling_settings = assertBlingToken();
    $bling_antiga['apikey'] = $bling_settings['13597']['apikey'];
    $bling_nova['apikey'] = $bling_settings['54533']['apikey'];
} catch (Exception $e) {
    error_log("Erro ao buscar configurações do Bling: " . $e->getMessage());
    die("Falha ao buscar configurações do Bling. Por favor, verifique os logs.");
}


// --- Helper Functions ---
function getExistingShopeeOrders($dbh) {
    $stmt = $dbh->query("SELECT numeroLoja FROM bling_pedidos");
    return array_flip($stmt->fetchAll(PDO::FETCH_COLUMN, 0));
}

function insertOrder($dbh, $orderData) {
    $sql = "INSERT INTO bling_pedidos (
                numero, numeroLoja, data, contato, personalizado, bling_id, criado_em, atualizado_em
            ) VALUES (
                :numero, :numeroLoja, :data, :contato, :personalizado, :bling_id, NOW(), NOW()
            ) ON DUPLICATE KEY UPDATE 
                numeroLoja = VALUES(numeroLoja),
                data = VALUES(data),
                contato = VALUES(contato),
                bling_id = VALUES(bling_id),
                personalizado = VALUES(personalizado),
                atualizado_em = NOW()";
                
    $stmt = $dbh->prepare($sql);
    $stmt->execute([
        ':numero' => $orderData['numero'],
        ':numeroLoja' => $orderData['numeroLoja'],
        ':data' => $orderData['data'],
        ':contato' => $orderData['contato'],
        ':personalizado' => $orderData['personalizado'] ? 1 : 0,
        ':bling_id' => $orderData['bling_id']
    ]);
    
    $mysqlId = $dbh->lastInsertId() ?: $dbh->query("SELECT id FROM bling_pedidos WHERE numero = '" . $orderData['numero'] . "'")->fetchColumn();

    // --- Sincronização com Supabase ---
    $supabaseData = [
        'numero_pedido' => $orderData['numero'],
        'numero_loja'   => $orderData['numeroLoja'],
        'data_pedido'   => $orderData['data'],
        'contato'       => $orderData['contato'], // Já é JSON string no MySQL, mas Supabase quer objeto se for JSONB
        'personalizado' => (bool)$orderData['personalizado'],
        'bling_id'      => $orderData['bling_id'],
        'deletado'      => false,
        'atualizado_em' => date('c')
    ];
    // Tentar decodificar contato para enviar como objeto JSON para o Supabase (JSONB)
    $contatoObj = json_decode($orderData['contato'], true);
    if (json_last_error() === JSON_ERROR_NONE) {
        $supabaseData['contato'] = $contatoObj;
    }

    syncToSupabase('pedidos_bling', 'POST', $supabaseData, 'on_conflict=numero_pedido');

    return $mysqlId;
}

function insertOrderItem($dbh, $itemData) {
    $sql = "INSERT INTO bling_pedido_itens (
                pedido_id, bling_item_id, codigo, unidade, quantidade, valor, descricao, produto, personalizado, criado_em, atualizado_em
            ) VALUES (
                :pedido_id, :bling_item_id, :codigo, :unidade, :quantidade, :valor, :descricao, :produto, :personalizado, NOW(), NOW()
            ) ON DUPLICATE KEY UPDATE 
                bling_item_id = VALUES(bling_item_id),
                quantidade = VALUES(quantidade),
                valor = VALUES(valor),
                descricao = VALUES(descricao),
                produto = VALUES(produto),
                personalizado = VALUES(personalizado),
                atualizado_em = NOW()";
                
    $stmt = $dbh->prepare($sql);
    $stmt->execute([
        ':pedido_id' => $itemData['pedido_id'],
        ':bling_item_id' => $itemData['bling_item_id'],
        ':codigo' => $itemData['codigo'],
        ':unidade' => $itemData['unidade'],
        ':quantidade' => $itemData['quantidade'],
        ':valor' => $itemData['valor'],
        ':descricao' => $itemData['descricao'],
        ':produto' => $itemData['produto'],
        ':personalizado' => $itemData['personalizado'] ? 1 : 0
    ]);
    
    $mysqlId = $dbh->lastInsertId();

    // --- Sincronização com Supabase ---
    // Buscar o ID do pedido no Supabase baseado no MySQL pedido_id
    // Como os IDs podem ser diferentes, vamos usar o numero_pedido para reconciliar
    $stmt_num = $dbh->prepare("SELECT numero FROM bling_pedidos WHERE id = ?");
    $stmt_num->execute([$itemData['pedido_id']]);
    $numero_pedido = $stmt_num->fetchColumn();

    if ($numero_pedido) {
        $supabaseItemData = [
            'bling_item_id' => $itemData['bling_item_id'],
            'codigo'        => $itemData['codigo'],
            'unidade'       => $itemData['unidade'],
            'quantidade'    => (float)$itemData['quantidade'],
            'valor'         => (float)$itemData['valor'],
            'descricao'     => $itemData['descricao'],
            'personalizado' => (bool)$itemData['personalizado'],
            'atualizado_em' => date('c')
        ];

        $produtoObj = json_decode($itemData['produto'], true);
        if (json_last_error() === JSON_ERROR_NONE) {
            $supabaseItemData['produto'] = $produtoObj;
        }

        // Usar RPC ou subquery via API para vincular pelo numero_pedido é complexo no PostgREST direto
        // Mais fácil: Buscar o ID do pedido no Supabase primeiro
        $res = syncToSupabase('pedidos_bling', 'GET', [], 'select=id&numero_pedido=eq.' . $numero_pedido);
        $orders = json_decode($res['response'], true);
        
        if (!empty($orders) && isset($orders[0]['id'])) {
            $supabaseItemData['pedido_bling_id'] = $orders[0]['id'];
            syncToSupabase('itens_pedido_bling', 'POST', $supabaseItemData, 'on_conflict=bling_item_id');
        }
    }
    
    return $mysqlId;
}

function getBlingOrders($apikey, $data_inicial, $data_final, $id_situacao, $id_loja, $delay = 0.3) {
    $all_orders = ['data' => []];
    $pagina = 1;
    $max_pages = 50; // Safety break to prevent infinite loops

    while ($pagina <= $max_pages) {
        usleep((int)($delay * 1000000)); // Throttle request with microseconds

        // Construct URL with parameters
        $url = "https://api.bling.com.br/Api/v3/pedidos/vendas?" . http_build_query([
            'pagina' => $pagina,
            'dataInicial' => $data_inicial,
            'dataFinal' => $data_final,
            'idsSituacoes[]' => $id_situacao,
            'idLoja' => $id_loja,
            'limite' => 100 // Max allowed by Bling API
        ]);

        // logOrderUpdate("Fetching page $pagina: $url");
        
        $ch = curl_init();
        curl_setopt_array($ch, [
            CURLOPT_URL => $url,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'Accept: application/json',
                'Authorization: Bearer ' . $apikey
            ],
            CURLOPT_TIMEOUT => 30
        ]);
        
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curl_error = curl_error($ch);
        curl_close($ch);
        
        if ($curl_error) {
            logOrderUpdate("cURL error on page $pagina: " . $curl_error);
            return ['error' => "cURL Error: " . $curl_error, 'data' => $all_orders['data']];
        }
        
        if ($httpCode !== 200) {
            logOrderUpdate("HTTP Error {$httpCode} on page $pagina: " . $response);
            return ['error' => "HTTP {$httpCode}", 'data' => $all_orders['data']];
        }
        
        $result = json_decode($response, true);
        
        if (json_last_error() !== JSON_ERROR_NONE) {
            logOrderUpdate("JSON decode error on page $pagina: " . json_last_error_msg());
            return ['error' => 'JSON decode error', 'data' => $all_orders['data']];
        }
        
        if (!isset($result['data']) || !is_array($result['data'])) {
            if (isset($result['error'])) {
                logOrderUpdate("API error on page $pagina: " . print_r($result['error'], true));
                return ['error' => $result['error']['message'] ?? 'Unknown error', 'data' => $all_orders['data']];
            }
            // No more data
            break;
        }
        
        $orders_count = count($result['data']);
        // logOrderUpdate("Page $pagina: Fetched $orders_count orders");
        
        if ($orders_count > 0) {
            $all_orders['data'] = array_merge($all_orders['data'], $result['data']);
            
            // If we got fewer items than the limit, we've reached the last page
            if ($orders_count < 100) {
                break;
            }
            
            $pagina++;
        } else {
            // No more orders
            break;
        }
    }
    
    logOrderUpdate("Total orders fetched: " . count($all_orders['data']));
    return $all_orders;
}

function getBlingOrder($apikey, $id_pedido, $delay = 0.3) {
    $url = "https://api.bling.com.br/Api/v3/pedidos/vendas/" . $id_pedido;
    
    usleep((int)($delay * 1000000)); // Throttle request with microseconds

    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json',
        'Accept: application/json',
        'Authorization: Bearer ' . $apikey
    ]);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        logOrderUpdate("Erro ao buscar detalhes do pedido {$id_pedido}: HTTP {$httpCode}");
        return ['error' => "HTTP {$httpCode}"];
    }
    
    return json_decode($response, true);
}

function getBlingProduct($apikey, $id_produto, $delay = 0.3) {
    $url = "https://api.bling.com.br/Api/v3/produtos/" . $id_produto;

    usleep((int)($delay * 1000000)); // Throttle request with microseconds
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json',
        'Accept: application/json',
        'Authorization: Bearer ' . $apikey
    ]);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        logOrderUpdate("Erro ao buscar produto {$id_produto}: HTTP {$httpCode}");
        return ['error' => "HTTP {$httpCode}"];
    }
    
    return json_decode($response, true);
}

/**
 * Retrieve order number from Bling nova to keep consistence with what operators use to identify orders
 */
function getBlingOrderByShopeeId($apikey, $id_pedido_shopee, $delay = 0.3)
{
    $url = 'https://api.bling.com.br/Api/v3/pedidos/vendas?numerosLojas[]=' . $id_pedido_shopee;

    usleep((int)($delay * 1000000)); // Throttle request with microseconds

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_HTTPHEADER => [
            'Accept: application/json',
            'Authorization: Bearer ' . $apikey
        ],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20
    ]);

    $response = curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curl_error = curl_error($ch);
    curl_close($ch);

    if ($curl_error) {
        error_log("Erro cURL ao buscar pedido ID {$id_pedido_shopee}: " . $curl_error);
        return ['error' => "Erro cURL: " . $curl_error];
    }

    if ($http_code >= 400) {
        error_log("Erro HTTP {$http_code} ao buscar pedido ID {$id_pedido_shopee}. Resposta: " . $response);
        return ['error' => "HTTP Error {$http_code}."];
    }

    $result = json_decode($response, true);

    if (json_last_error() !== JSON_ERROR_NONE) {
        error_log("Erro ao decodificar JSON ao buscar pedido ID {$id_pedido_shopee}: " . json_last_error_msg() . ". Resposta: " . $response);
        return ['error' => "Erro ao decodificar JSON."];
    }

    // Optional: Check for Bling's specific error structure if applicable
    if (isset($result['error'])) {
        error_log("Erro ao buscar pedido ID {$id_pedido_shopee}: " . print_r($result['error'], true));
        return ['error' => "Erro ao buscar pedido: " . $result['error']['message'] ?? 'Erro desconhecido'];
    }

    return $result; // Contains ['data' => [...]] on success
}

function resetOrdersToProcess($dbh)
{
    // update bling_pedidos to deleted = 1 all records with deleted = 0 
    $stmt = $dbh->prepare("UPDATE bling_pedidos SET deletado = 1 WHERE deletado = 0");
    try {
        $stmt->execute();
        $rowCount = $stmt->rowCount();

        // --- Sincronização com Supabase ---
        // Marcar como deletado todos que não estão deletados
        syncToSupabase('pedidos_bling', 'PATCH', ['deletado' => true], 'deletado=eq.false');

        return $rowCount;
    } catch (PDOException $e) {
        error_log("Erro ao atualizar registros de pedidos para deleted = 1: " . $e->getMessage());
        return false;
    }
}

function assertBlingToken(array $cnpjs = ['13597', '54533']): array
{
    global $firestoreCredPath;

    try {
        $firestore = new FirestoreClient([
            'keyFilePath' => $firestoreCredPath
        ]);
        logOrderUpdate("Autenticação Firestore realizada com sucesso.");
    } catch (Exception $e) {
        logOrderUpdate("Erro na autenticação Firestore: " . $e->getMessage());
        throw new Exception("Falha na autenticação Firestore: " . $e->getMessage());
    }

    $settings = [];

    foreach ($cnpjs as $cnpj) {
        try {
            logOrderUpdate("Buscando token para CNPJ '{$cnpj}' no Firestore...");

            $query = $firestore->collection('bling_accounts')
                ->where('cnpj', '==', $cnpj)
                ->orderBy('updated_at', 'DESC')
                ->limit(1);
            $snapshot = $query->documents();

            if ($snapshot->isEmpty()) {
                logOrderUpdate("Nenhum token encontrado para CNPJ '{$cnpj}'.");
                continue;
            }

            $tokenData = $snapshot->rows()[0]->data();
            $accessToken = $tokenData['access_token'];

            if (empty($accessToken)) {
                logOrderUpdate("Token vazio encontrado para CNPJ '{$cnpj}'.");
                continue;
            }

            $settings[$cnpj]['apikey'] = $accessToken;
            logOrderUpdate("Token obtido com sucesso para CNPJ '{$cnpj}'.");

        } catch (Exception $e) {
            logOrderUpdate("Erro no processo de token para CNPJ '{$cnpj}': " . $e->getMessage());
        }
    }

    $totalTokens = count($settings);
    logOrderUpdate("Processo de autenticação concluído. {$totalTokens} tokens obtidos de " . count($cnpjs) . " CNPJs consultados.");

    return $settings;
}

// --- Main Execution ---

try {
    resetOrdersToProcess($dbh);
} catch (Exception $e) {
    logOrderUpdate("Erro ao resetar pedidos: " . $e->getMessage());
}

try {
    logOrderUpdate("Iniciando atualização de pedidos...");
    
    // Get existing order numbers to avoid duplicates
    $existingOrderNumbers = getExistingShopeeOrders($dbh);
    logOrderUpdate(count($existingOrderNumbers) . " pedidos existentes.");

    // Fetch orders from Bling API
    logOrderUpdate("Buscando pedidos da Bling.");
    $bling_orders_response = getBlingOrders(
        $bling_antiga['apikey'], 
        $data_inicial, 
        $data_final, 
        $bling_antiga['open_status'], 
        $bling_antiga['shopee_store_id_bling']
    );

    if (!isset($bling_orders_response['data']) || !is_array($bling_orders_response['data'])) {
        die("Erro ao buscar pedidos da Bling ou nenhum pedido encontrado.");
    }

    logOrderUpdate(count($bling_orders_response['data']) . " pedidos na Bling.");

    // Filter out orders that already exist in our database or whose name contains **
    $new_orders = [];
    foreach ($bling_orders_response['data'] as $order) {
        if (!isset($existingOrderNumbers[$order['numeroLoja']]) && (!isset($order['contato']['nome']) || strpos($order['contato']['nome'], '**') === false)) {
            $new_orders[] = $order;
        }
    }
    logOrderUpdate(count($new_orders) . " novos pedidos encontrados.");

    $personalized_orders = $total_orders = count($new_orders);
    
    // Process each new order
    foreach ($new_orders as $index => $order_summary) {
        // add index/total to the logs. like 1/30
        logOrderUpdate("Processando pedido Shopee: {" . $order_summary['numeroLoja'] . "} (" . ($index + 1) . "/" . $total_orders . ")");
        
        usleep((int)($api_throttle_delay * 1000000));
        $full_order_data_response = getBlingOrder($bling_antiga['apikey'], $order_summary['id']);

        if (!isset($full_order_data_response['data']['itens'])) {
            logOrderUpdate("Aviso: Não foi possível buscar itens para o pedido {" . $order_summary['numero'] . "}. Pulando.");
            continue;
        }

        $full_order_data = $full_order_data_response['data'];

        $items_from_bling = $full_order_data['itens'];
        $hasPersonalizedItem = false;

        // Prepare order data for insertion
        $orderData = [
            'numero' => $full_order_data['numero'],
            'numeroLoja' => $full_order_data['numeroLoja'] ?? null,
            'data' => $full_order_data['data'],
            'contato' => json_encode($full_order_data['contato'] ?? []),
            'personalizado' => false
        ];

        // $temp_data = getBlingOrderByShopeeId($bling_nova['apikey'], $orderData['numeroLoja']);

        // logOrderUpdate(json_encode($temp_data));
        
        if($full_order_data['situacao']['id'] != 15){
            logOrderUpdate("Aviso: Pedido {" . $orderData['numeroLoja'] . "} não está em andamento. Pulando.");
            continue;
        }

        // $orderData['bling_id'] = $temp_data['data'][0]['id'];
        $orderData['bling_id'] = $full_order_data['id'];
        // $orderData['numero'] = $temp_data['data'][0]['numero'];
        // $orderData['numeroLoja'] = $temp_data['data'][0]['numeroLoja'];

        // Order insertion is now handled after checking for personalized items

        // First, check if any item is personalized
        $hasPersonalizedItem = false;
        $itemsData = [];
        
        foreach ($items_from_bling as $item) {
            $product_id = $item['produto']['id'] ?? 0;
            $isPersonalized = false;
            
            // Check if product is personalized
            if ($product_id > 0) {
                usleep((int)($api_throttle_delay * 1000000));
                $product_data_response = getBlingProduct($bling_antiga['apikey'], $product_id);
                
                if (isset($product_data_response['data']['camposCustomizados'])) {
                    foreach ($product_data_response['data']['camposCustomizados'] as $custom_field) {
                        if (isset($custom_field['idCampoCustomizado'], $custom_field['valor']) &&
                            $custom_field['idCampoCustomizado'] == $bling_antiga['id_custom_column_bling'] &&
                            strtolower($custom_field['valor']) === "true") {
                            $isPersonalized = true;
                            $hasPersonalizedItem = true;
                            break;
                        }
                    }
                }
            } elseif (stripos($item['descricao'] ?? '', 'personaliza') !== false) {
                $isPersonalized = true;
                $hasPersonalizedItem = true;
            }
            
            // Store item data for later insertion if needed
            $itemsData[] = [
                'item' => $item,
                'isPersonalized' => $isPersonalized,
                'product_data' => $product_data_response['data'] ?? []
            ];
        }
        
        // Only proceed with order insertion if it has at least one personalized item
        if (!$hasPersonalizedItem) {
            logOrderUpdate("Pedido {" . $orderData['numero'] . "} não contém itens personalizados. Pulando.");
            $personalized_orders--;
            continue;
        }
        
        // Mark order as personalized
        $orderData['personalizado'] = true;
        
        // Insert the order
        $orderId = insertOrder($dbh, $orderData);
        
        if (!$orderId) {
            logOrderUpdate("Erro ao inserir pedido {" . $orderData['numero'] . "} no banco de dados.");
            continue;
        }
        
        // SAFEGUARD: Double-check if order already exists in bling_pedidos before inserting items
        $stmt_check = $dbh->prepare("SELECT COUNT(*) FROM bling_pedidos WHERE numeroLoja = ?");
        $stmt_check->execute([$orderData['numeroLoja']]);
        $order_exists_now = $stmt_check->fetchColumn();
        if ($order_exists_now > 1) { // Should never be >1, but if so, skip
            logOrderUpdate("Pedido {" . $orderData['numeroLoja'] . "} já existe em bling_pedidos. Pulando inserção de itens.");
            continue;
        }
        // Process and insert items for the order
        foreach ($itemsData as $itemInfo) {
            $item = $itemInfo['item'];
            $isPersonalized = $itemInfo['isPersonalized'];
            $product_data = $itemInfo['product_data'];
            
            // Prepare item data for insertion
            $itemData = [
                'pedido_id' => $orderId,
                'bling_item_id' => $item['id'],
                'codigo' => $item['codigo'] ?? null,
                'unidade' => $item['unidade'] ?? 'UN',
                'quantidade' => $item['quantidade'] ?? 1,
                'valor' => $item['valor'] ?? 0,
                'descricao' => $item['descricao'] ?? '',
                'produto' => json_encode($item['produto'] ?? []),
                'personalizado' => $isPersonalized
            ];

            // Insert the order item
            $itemId = insertOrderItem($dbh, $itemData);
            
            if (!$itemId) {
                logOrderUpdate("Erro ao inserir item no pedido {" . $orderData['numero'] . "}.");
            } else {
                logOrderUpdate("Item {" . $itemData['descricao'] . "} inserido - (Personalizado: " . ($isPersonalized ? 'Sim' : 'Não') . ")");
            }
        }
        
        logOrderUpdate("Pedido {" . $orderData['numero'] . "} processado com sucesso.");
    }

    logOrderUpdate("Processamento concluído. {" . $personalized_orders . "} pedidos com itens personalizados dentre os " . $total_orders . " novos pedidos.");
    
} catch (Exception $e) {
    $error = "Erro durante o processamento: " . $e->getMessage();
    logOrderUpdate($error);
    die($error);
}

?>
