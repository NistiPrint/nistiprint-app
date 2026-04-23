// Try catch global para capturar erros
try {


document.addEventListener('DOMContentLoaded', function() {

    const platformSelect = document.getElementById('platform');
    const inputIdsTextarea = document.getElementById('inputIds');
    const outputContainer = document.getElementById('outputContainer');
    const selectAllBtn = document.getElementById('selectAllBtn');
    const convertBtn = document.getElementById('convertBtn');
    const spinner = convertBtn.querySelector('.spinner-border');

    const inputPanel = document.getElementById('inputPanel');
    const resultPanel = document.getElementById('resultPanel');
    const backBtn = document.getElementById('backBtn');

    const statusContainer = document.getElementById('statusContainer');
    const successAlert = document.getElementById('successAlert');
    const errorAlert = document.getElementById('errorAlert');
    const loadingAlert = document.getElementById('loadingAlert');
    const errorMessage = document.getElementById('errorMessage');

    const inputCount = document.getElementById('inputCount');
    const outputCount = document.getElementById('outputCount');
    const notFoundCount = document.getElementById('notFoundCount');

    // Função para contar IDs no textarea
    function updateInputCount() {
        const text = inputIdsTextarea.value.trim();
        const lines = text ? text.split('\n').filter(line => line.trim().length > 0) : [];
        inputCount.textContent = lines.length;
    }

    // Atualizar contador quando o usuário digita
    inputIdsTextarea.addEventListener('input', updateInputCount);
    inputIdsTextarea.addEventListener('paste', function() {
        setTimeout(updateInputCount, 0);
    });

    // Inicializar contador
    updateInputCount();

    // Converter IDs
    convertBtn.addEventListener('click', async function() {

        const platform = platformSelect.value;
        const inputText = inputIdsTextarea.value.trim();
        
        // Validações
        if (!platform) {
            showError('Selecione uma plataforma.');
            return;
        }

        if (!inputText) {
            showError('Cole os IDs dos pedidos no campo de origem.');
            return;
        }

        const orderIds = inputText.split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0);

        if (orderIds.length === 0) {
            showError('Nenhum ID válido encontrado.');
            return;
        }

        // Iniciar processamento
        setLoading(true);
        hideAlerts();

        try {
            const response = await fetch('/api/convert_order_ids', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    platform: platform,
                    order_ids: orderIds
                })
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || `Erro HTTP ${response.status}`);
            }

            if (!result.success) {
                throw new Error(result.error || 'Erro desconhecido na conversão');
            }

            // Sucesso
            setLoading(false);
            showSuccess();

            // Preencher resultados
            const tbody = document.querySelector('#outputTable tbody');
            tbody.innerHTML = ''; // limpar
            const convertedOrders = result.converted_orders;

            // Atualizar contadores
            const foundCount = convertedOrders.filter(order => order !== null).length;
            const notFound = convertedOrders.filter(order => order === null).length;

            outputCount.textContent = foundCount;
            notFoundCount.textContent = notFound;

            // Mostrar botão de copiar se há resultados
            if (convertedOrders.length > 0) {
                selectAllBtn.classList.remove('d-none');
            }

            // Adicionar cada resultado na tabela
            convertedOrders.forEach(order => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid #f0f0f0';

                if (order !== null && typeof order === 'object' && order.id && order.numero) {
                    const tdLoja = document.createElement('td');
                    tdLoja.textContent = order.numeroLoja || '';
                    tr.appendChild(tdLoja);

                    const tdBling = document.createElement('td');
                    const link = document.createElement('a');
                    link.href = `https://www.bling.com.br/vendas.php#edit/${order.id}`;
                    link.target = '_blank';
                    link.className = 'link-primary';
                    link.style.textDecoration = 'none';
                    link.textContent = order.numero;
                    tdBling.appendChild(link);
                    tr.appendChild(tdBling);
                } else {
                    const tdNotFound = document.createElement('td');
                    tdNotFound.colSpan = 2;
                    tdNotFound.className = 'text-muted text-center';
                    tdNotFound.textContent = '(não encontrado)';
                    tr.appendChild(tdNotFound);
                }

                tbody.appendChild(tr);
            });

            // Mostrar painel de resultado
            inputPanel.classList.add('d-none');
            resultPanel.classList.remove('d-none');

        } catch (error) {
            console.error('Erro na conversão:', error);
            setLoading(false);
            showError(error.message || 'Erro durante a conversão. Tente novamente.');
        }
    });

    // Funções de UI
    function setLoading(isLoading) {
        convertBtn.disabled = isLoading;

        if (isLoading) {
            spinner.classList.remove('d-none');
            convertBtn.textContent = ' Convertendo...';
        } else {
            spinner.classList.add('d-none');
            convertBtn.innerHTML = '<span class="spinner-border spinner-border-sm d-none"></span> Converter IDs';
        }
    }

    function showSuccess() {
        hideAlerts();
        statusContainer.classList.remove('d-none');
        successAlert.classList.remove('d-none');
        setTimeout(() => {
            successAlert.classList.add('d-none');
        }, 3000);
    }

    function showError(message) {
        hideAlerts();
        statusContainer.classList.remove('d-none');
        errorMessage.textContent = message;
        errorAlert.classList.remove('d-none');
    }

    function hideAlerts() {
        successAlert.classList.add('d-none');
        errorAlert.classList.add('d-none');
        loadingAlert.classList.add('d-none');
    }

    // Selecionar tudo (copiar para clipboard)
    selectAllBtn.addEventListener('click', async function() {
        try {
            const rows = document.querySelectorAll('#outputTable tbody tr');
            const resultLines = [];
            rows.forEach(row => {
                const link = row.querySelector('a');
                if (link) {
                    resultLines.push(link.textContent.trim());
                }
            });
            const textToCopy = resultLines.join('\n');

            if (textToCopy) {
                await navigator.clipboard.writeText(textToCopy);
                // Feedback visual temporário
                const originalText = selectAllBtn.innerHTML;
                selectAllBtn.innerHTML = '<i class="bi bi-check"></i> Copiado!';
                selectAllBtn.classList.remove('btn-outline-secondary');
                selectAllBtn.classList.add('btn-success');
                setTimeout(() => {
                    selectAllBtn.innerHTML = originalText;
                    selectAllBtn.classList.remove('btn-success');
                    selectAllBtn.classList.add('btn-outline-secondary');
                }, 2000);
            }
        } catch (error) {
            console.error('Erro ao copiar:', error);
            // Fallback para navegadores que não suportam clipboard API
            const rows = document.querySelectorAll('#outputTable tbody tr');
            const resultLines = [];
            rows.forEach(row => {
                const link = row.querySelector('a');
                if (link) {
                    resultLines.push(link.textContent.trim());
                }
            });
            const textToCopy = resultLines.join('\n');
            if (textToCopy) {
                // Criar textarea temporário para copiar
                const tempTextarea = document.createElement('textarea');
                tempTextarea.value = textToCopy;
                document.body.appendChild(tempTextarea);
                tempTextarea.select();
                document.execCommand('copy');
                document.body.removeChild(tempTextarea);
                showSuccess(); // usar o sucesso existente como feedback
            }
        }
    });

    // Voltar para entrada
    backBtn.addEventListener('click', function() {
        resultPanel.classList.add('d-none');
        inputPanel.classList.remove('d-none');
        // Limpar resultados
        document.querySelector('#outputTable tbody').innerHTML = '';
        selectAllBtn.classList.add('d-none');
        outputCount.textContent = '0';
        notFoundCount.textContent = '0';
        hideAlerts();
    });

    // Limpar resultados quando plataforma muda
    platformSelect.addEventListener('change', function() {
        if (resultPanel.classList.contains('d-none')) return; // só limpar se em resultado
        document.querySelector('#outputTable tbody').innerHTML = '';
        selectAllBtn.classList.add('d-none');
        outputCount.textContent = '0';
        notFoundCount.textContent = '0';
        hideAlerts();
    });
});

} catch (error) {
    console.error('❌ Erro global no JavaScript de conversão:', error);
}
