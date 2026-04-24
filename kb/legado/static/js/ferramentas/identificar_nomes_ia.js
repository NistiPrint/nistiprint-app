$(document).ready(function() {
    let resultsVisible = false;
    let logsVisible = false;

    // Handle form submission
    $('#processForm').on('submit', function(e) {
        e.preventDefault();

        const limit = $('#limit').val();
        const shopee_order_sn = $('#shopee_order_sn').val();

        // Disable button and show loading
        $('#processBtn').prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Processando...');

        // Show results section
        $('#resultsSection').show();
        $('#resultsContent').html(`
            <div class="text-center">
                <div class="spinner-border text-primary" role="status" style="width: 3rem; height: 3rem;">
                    <span class="sr-only">Processando...</span>
                </div>
                <p class="mt-3">Iniciando processamento de pedidos com IA...<br>
                <small class="text-muted">Isso pode levar alguns minutos dependendo do volume de pedidos.</small></p>
            </div>
        `);

        resultsVisible = true;

        // Send AJAX request
        $.ajax({
            url: '/ferramentas/processar_nomes_ia',
            method: 'POST',
            data: {
                limit: limit,
                shopee_order_sn: shopee_order_sn
            },
            success: function(response) {
                // Enable button
                $('#processBtn').prop('disabled', false).html('<i class="fas fa-play"></i> Iniciar Processamento IA');

                if (response.success) {
                    showSuccessMessage(response.message);
                    showLogsSection();
                } else {
                    showErrorMessage(response.message);
                }
            },
            error: function(xhr, status, error) {
                // Enable button
                $('#processBtn').prop('disabled', false).html('<i class="fas fa-play"></i> Iniciar Processamento IA');

                // Check for authentication error
                if (xhr.status === 401) {
                    showErrorMessage('Sessão expirada. Faça login novamente.');
                } else {
                    showErrorMessage('Erro interno do servidor. Tente novamente.');
                }
            }
        });
    });

    // Handle refresh logs button
    $('#refreshLogsBtn').on('click', function() {
        refreshLogs();
    });

    function showSuccessMessage(message) {
        $('#resultsContent').html(`
            <div class="alert alert-success">
                <h6><i class="fas fa-check-circle"></i> Sucesso!</h6>
                <p>${message}</p>
            </div>
        `);
    }

    function showErrorMessage(message) {
        $('#resultsContent').html(`
            <div class="alert alert-danger">
                <h6><i class="fas fa-exclamation-triangle"></i> Erro!</h6>
                <p>${message}</p>
            </div>
        `);
    }

    function showLogsSection() {
        if (!logsVisible) {
            $('#logsSection').show();
            logsVisible = true;
            refreshLogs();
        }
    }

    function refreshLogs() {
        if (!logsVisible) return;

        $('#logsContent').html('<p>Carregando logs...</p>');

        // In a real implementation, you would fetch logs from the server
        // For now, just show a placeholder
        setTimeout(function() {
            $('#logsContent').html(`
                <div class="text-success">[INFO] Starting order processing...</div>
                <div class="text-success">[INFO] Found orders to process</div>
                <div class="text-success">[INFO] Processing order... (Order SN: ...)</div>
                <div class="text-success">[INFO] Successfully saved extraction results</div>
                <div class="text-success">[INFO] Order processing completed.</div>
                <div class="text-muted">[Logs em tempo real serão implementados em uma versão futura]</div>
            `);
        }, 1000);
    }

    // Initialize tooltips if Bootstrap tooltips are used
    $('[data-toggle="tooltip"]').tooltip();

    console.log('Identificação de Nomes IA - Script loaded');
});
