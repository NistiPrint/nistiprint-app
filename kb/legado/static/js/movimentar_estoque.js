document.addEventListener('DOMContentLoaded', function () {
    const productSelect = $('#produto_id');
    const depositoSelect = $('#deposito_id');
    const tipoMovimentoSelect = $('#tipo_movimento');
    const depositoDestinoField = $('#deposito_destino_field');
    const depositoDestinoSelect = $('#deposito_destino_id');

    // Inicializa o Select2 para busca de produtos
    productSelect.select2({
        placeholder: 'Buscar produto por nome ou SKU...',
        ajax: {
            url: '/estoque/api/produtos-busca',
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    q: params.term, // Termo da busca
                    deposito_id: depositoSelect.val() // Filtrar por depósito selecionado
                };
            },
            processResults: function (data) {
                return {
                    results: data.results
                };
            },
            cache: true
        },
        minimumInputLength: 2
    });

    // Função para buscar e atualizar as informações do produto
    async function atualizarInfoProduto(produtoId, depositoId) {
        const saldoAtualEl = document.getElementById('saldo-atual');
        saldoAtualEl.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

        try {
            const saldoResponse = await fetch(`/estoque/api/saldo/${produtoId}/${depositoId}`);
            if (!saldoResponse.ok) { throw new Error('Falha ao buscar saldo.'); }
            const saldoData = await saldoResponse.json();
            saldoAtualEl.textContent = saldoData.quantidade || 0;
        } catch (error) {
            console.error('Erro ao buscar informações do produto:', error);
            saldoAtualEl.textContent = 'Erro';
        }
    }

    // Event listener para quando um produto é selecionado ou depósito muda
    function handleProductOrDepositoChange() {
        const produtoId = productSelect.val();
        const depositoId = depositoSelect.val();
        
        if (produtoId && depositoId) {
            atualizarInfoProduto(produtoId, depositoId);
        } else {
            document.getElementById('saldo-atual').textContent = '-';
        }
    }

    productSelect.on('select2:select', handleProductOrDepositoChange);
    depositoSelect.on('change', handleProductOrDepositoChange);

    // Lógica para mostrar/esconder o campo de depósito de destino
    tipoMovimentoSelect.on('change', function() {
        if ($(this).val() === 'TRANSFERENCIA') {
            depositoDestinoField.show();
            depositoDestinoSelect.prop('required', true);
        } else {
            depositoDestinoField.hide();
            depositoDestinoSelect.prop('required', false);
        }
    });
    // Disparar no carregamento inicial caso o tipo já seja TRANSFERENCIA
    tipoMovimentoSelect.trigger('change');


    // Handler para submissão do formulário
    const form = document.getElementById('form-movimentacao');
    form.addEventListener('submit', async function(event) {
        event.preventDefault();
        const submitButton = this.querySelector('button[type="submit"]');

        const formData = {
            produto_id: productSelect.val(),
            deposito_id: depositoSelect.val(),
            tipo_movimento: tipoMovimentoSelect.val(),
            quantidade: $('#quantidade').val(),
            observacao: $('#observacao').val(),
        };

        // Adiciona depósito de destino se for transferência
        if (formData.tipo_movimento === 'TRANSFERENCIA') {
            formData.deposito_destino_id = depositoDestinoSelect.val();
            if (formData.deposito_id === formData.deposito_destino_id) {
                showToast('Depósito de origem e destino não podem ser iguais.', 'warning');
                return;
            }
        }

        if (!formData.produto_id || !formData.deposito_id || !formData.quantidade) {
            showToast('Preencha todos os campos obrigatórios.', 'warning');
            return;
        }

        submitButton.disabled = true;
        submitButton.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Salvando...';

        try {
            const response = await fetch('/estoque/movimentar', { // POST para a própria rota /estoque/movimentar
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const result = await response.json();

            if (response.ok && result.success) {
                showToast(result.message, 'success');
                // Limpa campos para nova entrada
                $('#quantidade').val('');
                $('#observacao').val('');
                document.getElementById('saldo-atual').textContent = result.novo_saldo; // Atualiza saldo
                // Redireciona para o histórico do produto
                window.location.href = `/estoque/historico?produto_id=${formData.produto_id}`;
            } else {
                throw new Error(result.error || 'Erro desconhecido ao salvar.');
            }
        } catch (error) {
            showToast(error.message, 'danger');
        } finally {
            submitButton.disabled = false;
            submitButton.innerHTML = '<i class="fas fa-save"></i> Salvar Movimentação';
        }
    });
});