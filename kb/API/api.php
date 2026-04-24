<?php

// --- Logging Function ---
function log_api_event($type, $data, $isError = false)
{
    $logfile = __DIR__ . '/api.log';
    $timestamp = date('Y-m-d H:i:s');

    // Redact sensitive information
    $redactedData = $data;
    $sensitiveFields = ['api_token', 'password', 'token', 'authorization'];

    foreach ($sensitiveFields as $field) {
        if (isset($redactedData[$field])) {
            $redactedData[$field] = '[REDACTED]';
        }
        // Check nested arrays
        if (isset($redactedData['headers'])) {
            foreach ($redactedData['headers'] as $header => $value) {
                if (stripos($header, 'auth') !== false || in_array(strtolower($header), $sensitiveFields)) {
                    $redactedData['headers'][$header] = '[REDACTED]';
                }
            }
        }
    }

    // For non-error logs, reduce verbosity
    if (!$isError) {
        // Keep only essential information for successful requests
        $logData = [
            'endpoint' => $_SERVER['REQUEST_URI'] ?? '',
            'method' => $_SERVER['REQUEST_METHOD'] ?? 'UNKNOWN',
            'status' => $data['status'] ?? 'unknown'
        ];

        // For successful responses, just log the status
        if ($type === 'RESPONSE' && isset($data['status']) && $data['status'] < 400) {
            $logData = array_merge($logData, [
                'success' => true,
                'message' => 'Request processed successfully'
            ]);
        } else {
            // For other non-error logs, include minimal data
            $logData = $redactedData;
        }
    } else {
        // For errors, include full details
        $logData = $redactedData;
    }

    // Convert to JSON with pretty print for errors, compact for regular logs
    $jsonOptions = $isError ? (JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) : JSON_UNESCAPED_UNICODE;
    $log_entry = "[$timestamp] [$type] " . json_encode($logData, $jsonOptions) . PHP_EOL;

    // Rotate log file if it gets too large (e.g., 10MB)
    $maxLogSize = 10 * 1024 * 1024; // 10MB
    if (file_exists($logfile) && filesize($logfile) > $maxLogSize) {
        $backupFile = $logfile . '.' . date('Y-m-d_His');
        rename($logfile, $backupFile);
    }

    file_put_contents($logfile, $log_entry, FILE_APPEND);
}

// --- Load Secure Configuration ---
// Adjust the path based on where api.php is relative to your home directory's config folder
// Example: If api.php is in /home/user/public_html/api/ and secrets are in /home/user/config/
$appconfigPath = '/home/nistipri/appconfig/appconfig.php';
// Or use an absolute path (often more reliable but less portable):
// $appconfigPath = '/home/your_cpanel_username/config/api_secrets.php';

if (!file_exists($appconfigPath) || !is_readable($appconfigPath)) {
    // Log this critical error securely
    error_log("FATAL: API secrets file not found or not readable at: " . $appconfigPath);
    http_response_code(500); // Internal Server Error
    header('Content-Type: application/json'); // Ensure header is set even for early exit
    echo json_encode(['error' => 'Server configuration error. Please contact support.']);
    exit;
}

$appconfig = require $appconfigPath;

// Validate that required keys exist
if (empty($appconfig['api_token']) || empty($appconfig['db_host']) /* ... add other checks */) {
    error_log("FATAL: API secrets file is missing required keys.");
    http_response_code(500);
    header('Content-Type: application/json');
    echo json_encode(['error' => 'Server configuration error (incomplete).']);
    exit;
}

// --- Use Loaded Configuration ---
$db_host = $appconfig['db_host'];
$db_name = $appconfig['db_name'];
$db_user = $appconfig['db_user'];
$db_pass = $appconfig['db_pass'];
$expected_api_token = $appconfig['api_token'];
$db_charset = 'utf8mb4'; // Or move to secrets file too

// --- Supabase Configuration ---
$supabase_url = $appconfig['supabase_url'] ?? null;
$supabase_key = $appconfig['supabase_key'] ?? $appconfig['supabase_service_key'] ?? null;

// --- Start of your existing API code ---
header('Content-Type: application/json');

// --- Log Incoming Request (minimal) ---
log_api_event('REQUEST', [
    'method' => $_SERVER['REQUEST_METHOD'],
    'endpoint' => $_SERVER['REQUEST_URI'] ?? '',
    'timestamp' => date('c')
]);

// --- Security Token ---
// $expected_api_token is now loaded from the secrets file above

/**
 * Validates the API token from the request headers.
 *
 * @param string $expected_token The token the API expects.
 * @return bool True if the token is valid, false otherwise.
 */
function validateApiToken(string $expected_token): bool
{
    $auth_header = $_SERVER['HTTP_AUTHORIZATION'] ?? null;

    if (!$auth_header) {
        error_log("API Access Denied: Missing Authorization header.");
        return false;
    }

    // Check if the header format is Bearer <token>
    if (preg_match('/^Bearer\s+(.+)$/', $auth_header, $matches)) {
        $received_token = $matches[1];
        // Use hash_equals for timing-attack safe comparison
        if (hash_equals($expected_token, $received_token)) {
            return true;
        } else {
            error_log("API Access Denied: Invalid token received.");
            return false;
        }
    } else {
        error_log("API Access Denied: Invalid Authorization header format.");
        return false;
    }
}

// --- Security Check ---
if (!validateApiToken($expected_api_token)) {
    error_log("Header received: " . $_SERVER['HTTP_AUTHORIZATION']);
    http_response_code(401); // Unauthorized
    $resp = ['error' => 'Unauthorized access.'];
    log_api_event('RESPONSE', ['status' => 401, 'response' => $resp], true); // true for error
    echo json_encode($resp);
    exit;
}

/**
 * Establishes a database connection using PDO.
 *
 * @param string $host Database host
 * @param string $db   Database name
 * @param string $user Database username
 * @param string $pass Database password
 * @param string $charset Database charset
 * @return PDO|null Returns a PDO connection object on success, null on failure.
 */
function connectToDatabase(string $host, string $db, string $user, string $pass, string $charset = 'utf8mb4'): ?PDO
{
    $dsn = "mysql:host=$host;dbname=$db;charset=$charset";
    $options = [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ];

    try {
        $pdo = new PDO($dsn, $user, $pass, $options);
        $pdo->exec("SET NAMES 'utf8mb4'");
        return $pdo;
    } catch (\PDOException $e) {
        error_log("Database Connection Error: " . $e->getMessage());
        return null;
    }
}

/**
 * Executes a SQL query and fetches all results.
 *
 * @param PDO $pdo The PDO database connection object.
 * @param string $query The SQL query to execute.
 * @param array $params Optional parameters for prepared statements.
 * @return array|false Returns an array of results on success, false on failure.
 */
function queryDatabase(PDO $pdo, string $query, array $params = []): array|false // Added return type hint
{
    try {
        $stmt = $pdo->prepare($query);
        $stmt->execute($params);
        return $stmt->fetchAll();
    } catch (\PDOException $e) {
        error_log("Database Query Error: " . $e->getMessage());
        return false;
    }
}

/**
 * Synchronizes data to Supabase using its REST API.
 * 
 * @param string $table The table name in Supabase
 * @param string $method The HTTP method (POST, PATCH)
 * @param array $data The data to send
 * @param string|null $queryParams Optional parameters like on_conflict or filters
 * @return array Response status and data
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

    // Handle UPSERT preference if using POST with on_conflict
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

    // Log the sync attempt
    log_api_event('SUPABASE_SYNC', [
        'table' => $table,
        'method' => $method,
        'status' => $httpCode,
        'success' => $success,
        'error' => $curlError ?: ($success ? null : $response)
    ], !$success);

    return [
        'success' => $success,
        'status' => $httpCode,
        'response' => $response,
        'error' => $curlError
    ];
}


// Try to connect to the database (only after token validation)
$pdo = connectToDatabase($db_host, $db_name, $db_user, $db_pass, $db_charset);
if (!$pdo) {
    http_response_code(503);
    $resp = ['error' => 'Database connection failed.'];
    log_api_event('RESPONSE', ['status' => 503, 'response' => $resp], true);
    echo json_encode($resp);
    exit;
}

// --- API Endpoint Logic ---

// Handle Shopee Order from Chrome Extension (single order)
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_GET['action']) && $_GET['action'] === 'chrome_ext_send_order') {
    // Get JSON input
    $json_data = file_get_contents('php://input');
    $data = json_decode($json_data, true);

    // Log the incoming request
    log_api_event('REQUEST', [
        'endpoint' => 'chrome_ext_send_order',
        'data_received' => !empty($data),
        'data_type' => gettype($data)
    ]);

    // Validate input
    if (empty($data) || !isset($data['data']['package_card'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Invalid request data: Expected package_card']);
        exit;
    }

    try {
        $pdo = connectToDatabase($db_host, $db_name, $db_user, $db_pass, $db_charset);

        if (!$pdo) {
            throw new Exception('Database connection failed');
        }

        $package = $data['data']['package_card'] ?? [];
        $header = $package['card_header'] ?? [];
        $buyerInfo = $header['buyer_info'] ?? [];
        $itemInfo = $package['item_info_group'] ?? [];
        $orderExtInfo = $package['order_ext_info'] ?? [];

        // Extract order data
        $orderSn = $header['order_sn'] ?? '';
        $orderId = $orderExtInfo['order_id'] ?? 0;
        $message = $itemInfo['message'] ?? '';

        // Validate required fields
        if (empty($orderSn) || empty($orderId)) {
            $errorMsg = 'Missing required fields: order_sn or order_id';
            log_api_event('ERROR', ['message' => $errorMsg, 'data' => $data], true);
            http_response_code(400);
            echo json_encode(['error' => $errorMsg]);
            exit;
        }

        // Prepare data for insertion/update
        $buyerInfoJson = json_encode($buyerInfo, JSON_UNESCAPED_UNICODE);

        try {
            // Check if order exists
            $stmt = $pdo->prepare("SELECT order_sn FROM shopee_orders WHERE order_sn = ? OR order_id = ?");
            $stmt->execute([$orderSn, $orderId]);
            $exists = $stmt->fetch();

            if ($exists) {
                // Update existing order
                $stmt = $pdo->prepare("
                    UPDATE shopee_orders 
                    SET buyer_info = ?, 
                        message = ?,
                        updated_at = NOW()
                    WHERE order_sn = ? OR order_id = ?
                ");
                $stmt->execute([$buyerInfoJson, $message, $orderSn, $orderId]);
                $action = 'updated';
            } else {
                // Insert new order
                $stmt = $pdo->prepare("
                    INSERT INTO shopee_orders 
                    (order_sn, buyer_info, message, order_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, NOW(), NOW())
                ");
                $stmt->execute([$orderSn, $buyerInfoJson, $message, $orderId]);
                $action = 'inserted';
            }

            // Prepare success response
            $response = [
                'status' => 'success',
                'action' => $action,
                'order_sn' => $orderSn,
                'order_id' => $orderId
            ];

            // --- Sincronização com Supabase ---
            $supabaseOrderData = [
                'codigo_pedido'          => $orderSn,
                'informacoes_comprador'  => $buyerInfo, // Envia como array, syncToSupabase converterá para JSON
                'mensagem'               => $message,
                'id_pedido_shopee'       => $orderId,
                'updated_at'             => date('c')
            ];
            if ($action === 'inserted') {
                $supabaseOrderData['created_at'] = date('c');
                $supabaseOrderData['data_criacao'] = date('c');
            }
            syncToSupabase('pedidos_shopee', 'POST', $supabaseOrderData, 'on_conflict=codigo_pedido');
            // --- NOVO: Criar vínculo SHOPEE na tabela de integrações ---
            syncToSupabase('vinculos_integracao_pedido', 'POST', [ 'plataforma' => 'SHOPEE', 'id_na_plataforma' => $orderSn, 'dados_brutos' => ['informacoes_comprador' => $buyerInfo, 'mensagem' => $message, 'order_id' => $orderId]], 'on_conflict=plataforma,id_na_plataforma');

            http_response_code(200);
            header('Content-Type: application/json');
            echo json_encode($response);

            // Log successful processing
            log_api_event('ORDER_PROCESSED', [
                'status' => 'success',
                'action' => $action,
                'order_sn' => $orderSn,
                'order_id' => $orderId
            ]);
        } catch (PDOException $e) {
            $errorMsg = "Database error for order {$orderSn}: " . $e->getMessage();
            error_log("Shopee Order DB Error: " . $e->getMessage());

            http_response_code(500);
            echo json_encode(['error' => $errorMsg]);

            log_api_event('ORDER_ERROR', [
                'message' => $errorMsg,
                'order_sn' => $orderSn,
                'order_id' => $orderId
            ], true);
        }
    } catch (Exception $e) {
        $errorMsg = 'Server error: ' . $e->getMessage();
        http_response_code(500);
        echo json_encode(['error' => $errorMsg]);

        // Log the error
        log_api_event('ERROR', [
            'message' => $errorMsg,
            'trace' => $e->getTraceAsString()
        ], true);
    }

    exit;
}

// GET v2 orders with items (nested)
if ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['action']) && $_GET['action'] === 'v2_get_orders') {
    $sql = "
        SELECT
            o.id AS order_id,
            o.id_bling,
            o.bling_order_number,
            o.id_shopee,
            o.customer_name,
            o.customer_username_shopee,
            o.order_status,
            o.order_datetime,
            o.message_to_seller,
            o.id_shopee_internal,
            oi.id AS item_id,
            oi.id_product_bling,
            oi.product_sku,
            oi.product_name,
            oi.quantity,
            oi.price,
            oi.is_personalized,
            oi.match_type,
            oi.custom_name,
            oi.custom_initial,
            oi.notes
        FROM v2_orders o
        LEFT JOIN v2_order_items oi ON o.id = oi.order_id
        WHERE (o.is_deleted = 0 OR o.is_deleted IS NULL)
        ORDER BY o.order_datetime DESC, o.id DESC
    ";
    $stmt = $pdo->prepare($sql);
    $stmt->execute();
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    // Group items by order
    $orders = [];
    foreach ($rows as $row) {
        $oid = $row['order_id'];
        if (!isset($orders[$oid])) {
            $orders[$oid] = [
                'id' => $oid,
                'id_bling' => $row['id_bling'],
                'bling_order_number' => $row['bling_order_number'],
                'id_shopee' => $row['id_shopee'],
                'customer_name' => $row['customer_name'],
                'customer_username_shopee' => $row['customer_username_shopee'],
                'order_status' => $row['order_status'],
                'order_datetime' => $row['order_datetime'],
                'message_to_seller' => $row['message_to_seller'],
                'id_shopee_internal' => $row['id_shopee_internal'],
                'items' => []
            ];
        }
        if ($row['item_id']) {
            $orders[$oid]['items'][] = [
                'id' => $row['item_id'],
                'id_product_bling' => $row['id_product_bling'],
                'product_sku' => $row['product_sku'],
                'product_name' => $row['product_name'],
                'quantity' => $row['quantity'],
                'price' => $row['price'],
                'is_personalized' => $row['is_personalized'],
                'match_type' => $row['match_type'],
                'custom_name' => $row['custom_name'],
                'custom_initial' => $row['custom_initial'],
                'notes' => $row['notes']
            ];
        }
    }
    $orders = array_values($orders); // Reindex for JSON
    echo json_encode(['orders' => $orders]);
    exit;
} elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_GET['action']) && $_GET['action'] === 'v2_update_order_fields') {
    $json_data = file_get_contents('php://input');
    $data = json_decode($json_data, true);

    if (empty($data['id'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing required field: id']);
        exit;
    }

    $updates = [];
    $params = ['id' => $data['id']];

    if (isset($data['customer_username_shopee'])) {
        $updates[] = 'customer_username_shopee = :customer_username_shopee';
        $params['customer_username_shopee'] = $data['customer_username_shopee'];
    }
    if (isset($data['message_to_seller'])) {
        $updates[] = 'message_to_seller = :message_to_seller';
        $params['message_to_seller'] = $data['message_to_seller'];
    }
    if (isset($data['id_shopee_internal'])) {
        $updates[] = 'id_shopee_internal = :id_shopee_internal';
        $params['id_shopee_internal'] = $data['id_shopee_internal'];
    }

    if (empty($updates)) {
        http_response_code(400);
        echo json_encode(['error' => 'No fields to update']);
        exit;
    }

    try {
        $sql = "UPDATE v2_orders SET " . implode(', ', $updates) . " WHERE id = :id";
        $stmt = $pdo->prepare($sql);
        $result = $stmt->execute($params);
        $rowCount = $stmt->rowCount();

        // --- Sincronização com Supabase ---
        if ($result) {
            $supabaseUpdateData = $params;
            $orderId = $supabaseUpdateData['id'];
            unset($supabaseUpdateData['id']);
            syncToSupabase('pedidos_v2', 'PATCH', $supabaseUpdateData, 'id=eq.' . $orderId);
        }

        echo json_encode([
            'success' => $result,
            'rows_affected' => $rowCount
        ]);
    } catch (PDOException $e) {
        http_response_code(500);
        echo json_encode(['error' => 'Failed to update order', 'details' => $e->getMessage()]);
    }
    exit;
} elseif ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['action']) && $_GET['action'] === 'get_ai_order_messages') {
    $id_order = $_GET['id_order'] ?? null;

    if (!$id_order) {
        http_response_code(400);
        $resp = ['error' => 'Missing required parameter: id_order'];
        log_api_event('RESPONSE', ['status' => 400, 'response' => $resp]);
        echo json_encode($resp);
        exit;
    }

    // Get order details
    $order_query = "SELECT id_order, id_shopee, customer_name, product_name, customer_username_shopee
                   FROM orders_control 
                   WHERE id_order = :id_order";
    $order = queryDatabase($pdo, $order_query, ['id_order' => $id_order]);

    if (empty($order)) {
        http_response_code(404);
        $resp = ['error' => 'Order not found'];
        log_api_event('RESPONSE', ['status' => 404, 'response' => $resp]);
        echo json_encode($resp);
        exit;
    }

    $order = $order[0];

    // Get messages for this order
    $query = "SELECT 
                ce.id, 
                ce.from_user_name, 
                ce.to_user_name, 
                ce.content, 
                ce.created_at,
                ce.type
              FROM v2_chat_events ce
              JOIN orders_control o ON (ce.from_user_name = o.customer_username_shopee OR ce.to_user_name = o.customer_username_shopee)
              WHERE o.id_order = :id_order
              ORDER BY ce.created_at ASC";

    $messages = queryDatabase($pdo, $query, ['id_order' => $id_order]);

    if ($messages === false) {
        http_response_code(500);
        $resp = ['error' => 'Failed to retrieve messages from the database.'];
        log_api_event('RESPONSE', ['status' => 500, 'response' => $resp]);
        echo json_encode($resp);
        exit;
    }

    // Format the response
    $response = [
        'order' => [
            'id' => $order['id_order'],
            'id_shopee' => $order['id_shopee'],
            'customer_name' => $order['customer_name'],
            'product_name' => $order['product_name']
        ],
        'messages' => array_map(function ($msg) {
            return [
                'id' => $msg['id'],
                'from' => $msg['from_user_name'],
                'to' => $msg['to_user_name'],
                'content' => $msg['content'],
                'timestamp' => $msg['created_at'],
                'type' => $msg['type']
            ];
        }, $messages)
    ];

    echo json_encode($response);
    exit;
} elseif ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['action']) && $_GET['action'] === 'v2_get_process_queue') {
    // Select pending/unprocessed orders from v2_orders
    // - is_deleted = 0 or NULL
    // - (is_processed = 0) OR (is_processed = 1 AND (custom_name IS NULL OR custom_name = '' OR custom_name = 'N/A') AND order_status != 'revisar')
    $query = "SELECT 
                id AS id,
                id_bling,
                id_shopee,
                customer_name,
                order_status,
                is_processed,
                custom_name,
                custom_initial,
                customer_username_shopee,
                message_to_seller,
                id_shopee_internal
            FROM v2_orders
            WHERE (is_deleted = 0 OR is_deleted IS NULL)
              AND (
                    is_processed = 0
                    OR (
                        is_processed = 1
                        AND (custom_name IS NULL OR custom_name = '' OR custom_name = 'N/A')
                        AND (order_status IS NULL OR order_status != 'revisar')
                    )
                )
            ORDER BY order_datetime ASC, id ASC";

    $result = queryDatabase($pdo, $query);

    if ($result !== false) {
        echo json_encode(['orders' => $result]);
    } else {
        http_response_code(500);
        $resp = ['error' => 'Failed to retrieve data from the database.'];
        log_api_event('RESPONSE', ['status' => 500, 'response' => $resp]);
        echo json_encode($resp);
    }
} elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_GET['action']) && $_GET['action'] === 'chrome_ext_send_messages') {
    // ---------------------------------------------------------------------------------
    // Endpoint: chrome_ext_send_messages
    // Receives an array of Shopee chat message objects from the Chrome extension and
    // persists them into `v2_chat_events` (+ `v2_bundle_messages` when applicable).
    // ---------------------------------------------------------------------------------
    $json_data = file_get_contents('php://input');
    $data = json_decode($json_data, true);

    log_api_event('REQUEST', ['action' => 'chrome_ext_send_messages', 'data' => $data]);

    if ($data === null && json_last_error() !== JSON_ERROR_NONE) {
        http_response_code(400);
        $resp = ['error' => 'Invalid JSON payload: ' . json_last_error_msg()];
        log_api_event('RESPONSE', ['status' => 400, 'response' => $resp]);
        echo json_encode($resp);
        exit;
    }

    // The payload is now a direct array of messages
    $messages = [];

    // Log the raw input data for debugging
    log_api_event('RAW_INPUT', ['data' => $data, 'data_type' => gettype($data)]);

    // The entire payload should be an array of messages
    if (is_array($data)) {
        // If it's an associative array with numeric keys, it's already our messages array
        if (array_values($data) === $data) {
            $messages = $data;
        } else {
            // If it's an object/associative array, wrap it in an array
            $messages = [$data];
        }
        log_api_event('MESSAGES_RECEIVED', ['count' => count($messages)]);
    } else {
        // If not an array, try to decode it as JSON
        if (is_string($data) && (strpos($data, '[') === 0 || strpos($data, '{') === 0)) {
            $decoded = json_decode($data, true);
            if (json_last_error() === JSON_ERROR_NONE) {
                $messages = is_array($decoded) ? (array_values($decoded) === $decoded ? $decoded : [$decoded]) : [];
                log_api_event('JSON_DECODED', ['count' => count($messages)]);
            } else {
                log_api_event('JSON_DECODE_ERROR', [
                    'error' => json_last_error_msg(),
                    'input' => $data
                ]);
            }
        } else {
            // If it's a scalar value, wrap it in an array
            $messages = [$data];
        }
    }

    // Log the processed messages for debugging
    log_api_event('PROCESSED_MESSAGES', [
        'count' => count($messages),
        'first_message_type' => !empty($messages) ? gettype($messages[0]) : 'empty',
        'is_array' => !empty($messages) && is_array($messages[0]) ? 'yes' : 'no',
        'first_message_keys' => !empty($messages) && is_array($messages[0]) ? array_keys($messages[0]) : []
    ]);

    if (empty($messages)) {
        http_response_code(400);
        $resp = ['error' => 'No valid messages found in the payload.'];
        log_api_event('RESPONSE', ['status' => 400, 'response' => $resp]);
        echo json_encode($resp);
        exit;
    }
    log_api_event('INFO', ['action' => 'chrome_ext_send_messages', 'count' => count($messages)]);

    // --- Prepare SQL -----------------------------------------------------------------
    $insertEventSQL = "INSERT INTO v2_chat_events (
            id, shop_id, request_id, from_id, to_id, from_shop_id, to_shop_id,
            from_user_name, to_user_name, type, conversation_id,
            faq_session_id, source_type, created_timestamp, created_at,
            status, message_option, source, content, faq_info,
            source_content, raw_json
        ) VALUES (
            :id, :shop_id, :request_id, :from_id, :to_id, :from_shop_id, :to_shop_id,
            :from_user_name, :to_user_name, :type, :conversation_id,
            :faq_session_id, :source_type, FROM_UNIXTIME(:created_timestamp), :created_at,
            :status, :message_option, :source, :content, :faq_info,
            :source_content, :raw_json
        ) ON DUPLICATE KEY UPDATE raw_json = VALUES(raw_json), type = VALUES(type)";

    $insertBundleSQL = "INSERT IGNORE INTO v2_bundle_messages (event_id, msg_id)
                        VALUES (:event_id, :msg_id)";

    $pdo->beginTransaction();
    try {
        $eventStmt   = $pdo->prepare($insertEventSQL);
        $bundleStmt  = $pdo->prepare($insertBundleSQL);

        $inserted    = 0;
        foreach ($messages as $msg) {
            // Basic required field check
            if (!isset($msg['id']) || !isset($msg['type'])) {
                continue; // skip invalid row but keep processing others
            }

            // Handle datetime format - preserve timezone information
            $createdAt = $msg['created_at'] ?? null;
            if ($createdAt) {
                // Convert from "2025-05-28T07:30:32-02:00" to "2025-05-28 07:30:32" in UTC
                $dt = new DateTime($createdAt);
                $dt->setTimezone(new DateTimeZone('UTC'));
                $createdAt = $dt->format('Y-m-d H:i:s');
            }

            // Map scalar + JSON fields -------------------------------------------------
            $params = [
                ':id'                      => (string)$msg['id'],
                ':shop_id'                 => $msg['shop_id']          ?? null,
                ':request_id'              => $msg['request_id']       ?? null,
                ':from_id'                 => $msg['from_id']          ?? null,
                ':to_id'                   => $msg['to_id']            ?? null,
                ':from_shop_id'            => $msg['from_shop_id']     ?? null,
                ':to_shop_id'              => $msg['to_shop_id']       ?? null,
                ':from_user_name'          => $msg['from_user_name']    ?? null,
                ':to_user_name'            => $msg['to_user_name']      ?? null,
                ':type'              => $msg['type'],
                ':conversation_id'   => $msg['conversation_id']   ?? null,
                ':faq_session_id'    => $msg['faq_session_id']    ?? null,
                ':source_type'       => $msg['source_type']       ?? null,
                ':created_timestamp' => $msg['created_timestamp'] ?? null,
                ':created_at'        => $createdAt,
                ':status'            => $msg['status']            ?? null,
                ':message_option'    => $msg['message_option']    ?? null,
                ':source'            => $msg['source']            ?? null,
                ':content'           => isset($msg['content']) ? json_encode($msg['content']) : null,
                ':faq_info'          => isset($msg['faq_info']) ? json_encode($msg['faq_info']) : null,
                ':source_content'    => isset($msg['source_content']) ? json_encode($msg['source_content']) : null,
                ':raw_json'                => json_encode($msg, JSON_UNESCAPED_UNICODE)
            ];

            $eventStmt->execute($params);
            $inserted += $eventStmt->rowCount();

            // --- Sincronização com Supabase (Eventos) ---
            $supabaseEventData = [
                'id'                 => (string)$msg['id'],
                'shop_id'            => $msg['shop_id']          ?? null,
                'request_id'         => $msg['request_id']       ?? null,
                'from_id'            => $msg['from_id']          ?? null,
                'to_id'              => $msg['to_id']            ?? null,
                'from_shop_id'       => $msg['from_shop_id']     ?? null,
                'to_shop_id'         => $msg['to_shop_id']       ?? null,
                'from_user_name'     => $msg['from_user_name']    ?? null,
                'to_user_name'       => $msg['to_user_name']      ?? null,
                'type'               => $msg['type'],
                'conversation_id'    => $msg['conversation_id']   ?? null,
                'faq_session_id'     => $msg['faq_session_id']    ?? null,
                'source_type'        => $msg['source_type']       ?? null,
                'created_timestamp'  => isset($msg['created_timestamp']) ? date('c', (int)$msg['created_timestamp']) : null,
                'created_at'         => $createdAt,
                'status'             => $msg['status']            ?? null,
                'message_option'     => $msg['message_option']    ?? null,
                'source'             => $msg['source']            ?? null,
                'content'            => $msg['content']           ?? null,
                'faq_info'           => $msg['faq_info']          ?? null,
                'source_content'     => $msg['source_content']    ?? null,
                'raw_json'           => $msg
            ];
            syncToSupabase('mensagem_chat_shopee', 'POST', $supabaseEventData, 'on_conflict=id');

            // --- Bundle messages ------------------------------------------------------
            if ($msg['type'] === 'bundle_message' && isset($msg['content']['messages']) && is_array($msg['content']['messages'])) {
                foreach ($msg['content']['messages'] as $childId) {
                    $bundleStmt->execute([
                        ':event_id' => (string)$msg['id'],
                        ':msg_id'   => (string)$childId
                    ]);

                    // --- Sincronização com Supabase (Bundle) ---
                    syncToSupabase('grupo_mensagens_chat_shopee', 'POST', [
                        'event_id' => (string)$msg['id'],
                        'msg_id'   => (string)$childId
                    ], 'on_conflict=event_id,msg_id');
                }
            }
        }
        $pdo->commit();

        $resp = ['success' => true, 'inserted_events' => $inserted];
        log_api_event('RESPONSE', ['status' => 200, 'response' => $resp]);
        echo json_encode($resp);
    } catch (Exception $e) {
        $pdo->rollBack();
        error_log('chrome_ext_send_messages error: ' . $e->getMessage());
        http_response_code(500);
        $resp = ['error' => 'Failed to persist messages', 'details' => $e->getMessage()];
        log_api_event('RESPONSE', ['status' => 500, 'response' => $resp], true);
        echo json_encode($resp);
    }
} elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_GET['action']) && $_GET['action'] === 'update_order_fields') {
    // Get JSON input
    $json_data = file_get_contents('php://input');
    $data = json_decode($json_data, true);

    // --- Update Order Fields Endpoint ---
    log_api_event('RESULT', ['action' => 'update_order_fields', 'data' => $data]);

    // Validate required fields
    if (empty($data['id_order'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing required field: id_order']);
        exit;
    }

    // Prepare update fields
    $updates = [];
    $params = ['id_order' => $data['id_order']];

    // Check and add each field if present
    if (isset($data['customer_username_shopee'])) {
        $updates[] = 'customer_username_shopee = :customer_username_shopee';
        $params['customer_username_shopee'] = $data['customer_username_shopee'];
    }

    if (isset($data['message_to_seller'])) {
        $updates[] = 'message_to_seller = :message_to_seller';
        $params['message_to_seller'] = $data['message_to_seller'];
    }

    if (isset($data['id_shopee_internal'])) {
        $updates[] = 'id_shopee_internal = :id_shopee_internal';
        $params['id_shopee_internal'] = $data['id_shopee_internal'];
    }

    // If no fields to update
    if (empty($updates)) {
        http_response_code(400);
        echo json_encode(['error' => 'No fields to update']);
        exit;
    }

    try {
        // Build the SQL query
        $sql = "UPDATE orders_control SET " . implode(', ', $updates) . " WHERE id_order = :id_order";

        // Log the SQL query and parameters for debugging
        $logData = [
            'action' => 'update_order_fields',
            'sql' => $sql,
            'params' => $params,
            'id_order' => $data['id_order']
        ];
        log_api_event('DEBUG', $logData);

        // Execute the update
        $stmt = $pdo->prepare($sql);
        $result = $stmt->execute($params);
        $rowCount = $stmt->rowCount();

        // --- Sincronização com Supabase ---
        if ($result) {
            $supabaseUpdateData = $params;
            $idOrder = $supabaseUpdateData['id_order'];
            unset($supabaseUpdateData['id_order']);
            syncToSupabase('orders_control', 'PATCH', $supabaseUpdateData, 'id_order=eq.' . $idOrder);
        }

        $logData['rows_affected'] = $rowCount;

        if (!$result) {
            // This would mean the query failed
            log_api_event('ERROR', array_merge($logData, ['error' => 'Database error occurred']));
            http_response_code(500);
            echo json_encode(['error' => 'Failed to update order']);
        } elseif ($rowCount > 0) {
            // Rows were actually updated
            log_api_event('SUCCESS', $logData);
            echo json_encode([
                'success' => true,
                'message' => 'Order updated successfully',
                'changes_made' => true
            ]);
        } else {
            // No rows updated - could be because order doesn't exist or no changes were needed
            // First, verify if the order exists
            $checkStmt = $pdo->prepare("SELECT COUNT(*) FROM orders_control WHERE id_order = :id_order");
            $checkStmt->execute(['id_order' => $data['id_order']]);
            $orderExists = $checkStmt->fetchColumn() > 0;

            if (!$orderExists) {
                log_api_event('WARNING', array_merge($logData, ['error' => 'Order not found']));
                http_response_code(404);
                echo json_encode(['error' => 'Order not found']);
            } else {
                // Order exists but no changes were needed
                log_api_event('INFO', array_merge($logData, ['message' => 'No changes needed - data already up to date']));
                echo json_encode([
                    'success' => true,
                    'message' => 'No changes needed - data already up to date',
                    'changes_made' => false
                ]);
            }
        }
    } catch (PDOException $e) {
        http_response_code(500);
        error_log('Update order fields error: ' . $e->getMessage());
        echo json_encode(['error' => 'Failed to update order', 'details' => $e->getMessage()]);
    }
    exit;
}
# get orders from bling_orders
elseif ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['action']) && $_GET['action'] === 'get_bling_orders') {
    try {
        // select numero from bling_orders that doesn't exist in shopee_orders as column order_sn
        $sql = "SELECT numeroLoja FROM bling_pedidos WHERE deletado = 0";
        $stmt = $pdo->prepare($sql);
        $stmt->execute();
        $rowCount = $stmt->rowCount();
        $result = $stmt->fetchAll(PDO::FETCH_ASSOC);
        if (!$result) {
            http_response_code(500);
            $resp = ['error' => 'Failed to retrieve data from the database.'];
            log_api_event('RESPONSE', ['status' => 500, 'response' => $resp]);
            echo json_encode($resp);
        } elseif ($rowCount > 0) {
            // Transform the result to a simple array of order numbers
            $orderNumbers = array_column($result, 'numeroLoja');
            $resp = ['success' => true, 'orders' => $orderNumbers];
            log_api_event('RESPONSE', ['status' => 200, 'response' => $resp]);
            echo json_encode($resp);
        } else {
            http_response_code(500);
            $resp = ['error' => 'Failed to retrieve data from the database.'];
            log_api_event('RESPONSE', ['status' => 500, 'response' => $resp]);
            echo json_encode($resp);
        }
    } catch (PDOException $e) {
        http_response_code(500);
        error_log('Get bling orders error: ' . $e->getMessage());
        echo json_encode(['error' => 'Failed to retrieve data from the database', 'details' => $e->getMessage()]);
    }
    exit;
}