const bomManager = (() => {
    let config = {
        produtoId: null,
        searchUrl: '',
        bomUrl: '',
        applyTemplateUrl: ''
    };

    let bomState = []; // Array de objetos { component_id, sku, name, quantity, cost }

    const init = (newConfig) => {
        config = { ...config, ...newConfig };
        console.log("bomManager initialized with config:", config);
        
        if (config.produtoId) {
            loadInitialBom();
        }

        setupEventListeners();
        initComponentSearch();
    };

    const setupEventListeners = () => {
        $('#addComponentBtn').on('click', handleAddComponent);
        $('#bom-table-body').on('click', '.remove-component-btn', handleRemoveComponent);
        $('#bom-table-body').on('input', '.quantity-input', handleQuantityInputChange);
        $('#bom-table-body').on('click', '.update-quantity-btn', handleUpdateQuantity);
        $('#applyTemplateModal').on('click', '.apply-template-btn', handleApplyTemplate);
    };

    const handleQuantityInputChange = (event) => {
        const input = $(event.currentTarget);
        const componentId = input.data('component-id');
        const updateBtn = $(`.update-quantity-btn[data-component-id="${componentId}"]`);
        const originalQuantity = bomState.find(c => c.component_id === componentId).original_quantity;
        
        if (parseFloat(input.val()) !== originalQuantity) {
            updateBtn.show();
        } else {
            updateBtn.hide();
        }
    };

    const handleUpdateQuantity = (event) => {
        const button = $(event.currentTarget);
        const componentId = button.data('component-id');
        const newQuantity = parseFloat($(`.quantity-input[data-component-id="${componentId}"]`).val());

        if (isNaN(newQuantity) || newQuantity <= 0) {
            alert('A quantidade deve ser um número positivo.');
            return;
        }

        $.ajax({
            url: config.bomUrl,
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ component_id: componentId, quantity: newQuantity }),
            success: () => {
                const item = bomState.find(c => c.component_id === componentId);
                item.quantity = newQuantity;
                item.original_quantity = newQuantity;
                renderBomTable(); // Re-render to update total cost and hide button
            },
            error: (err) => {
                alert(err.responseJSON?.error || 'Falha ao atualizar a quantidade.');
                const item = bomState.find(c => c.component_id === componentId);
                $(`.quantity-input[data-component-id="${componentId}"]`).val(item.original_quantity);
            }
        });
    };

    const loadInitialBom = () => {
        if (!config.bomUrl) {
            console.error("BOM URL is not configured.");
            return;
        }

        $.ajax({
            url: config.bomUrl,
            method: 'GET',
            success: (data) => {
                if (data.components) {
                    bomState = data.components.map(c => ({ ...c, original_quantity: c.quantity }));
                    renderBomTable();
                }
            },
            error: (err) => {
                console.error("Erro ao carregar BOM:", err);
                alert('Falha ao carregar a composição do produto.');
            }
        });
    };

    const renderBomTable = () => {
        const tableBody = $('#bom-table-body');
        const tableFoot = $('#bom-table-foot');
        const noComponentsMessage = $('#no-components-message');

        tableBody.empty();
        tableFoot.empty();

        if (bomState.length === 0) {
            noComponentsMessage.show();
            return;
        }

        noComponentsMessage.hide();
        let totalCost = 0;

        bomState.forEach(item => {
            const itemTotalCost = (item.quantity || 0) * (item.cost || 0);
            totalCost += itemTotalCost;
            const row = `
                <tr data-component-id="${item.component_id}">
                    <td>${item.sku}</td>
                    <td>${item.name}</td>
                    <td class="text-center">
                        <input type="number" class="form-control form-control-sm quantity-input" value="${item.quantity}" 
                               style="width: 100px; display: inline-block;" min="0.0001" step="0.0001" 
                               data-component-id="${item.component_id}">
                    </td>
                    <td class="text-center">${formatCurrency(item.cost)}</td>
                    <td class="text-center font-weight-bold">${formatCurrency(itemTotalCost)}</td>
                    <td class="text-center">
                        <button type="button" class="btn btn-success btn-sm update-quantity-btn" 
                                data-component-id="${item.component_id}" style="display: none;">
                            <i class="fas fa-check"></i>
                        </button>
                        <button type="button" class="btn btn-danger btn-sm remove-component-btn" 
                                data-component-id="${item.component_id}">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </td>
                </tr>
            `;
            tableBody.append(row);
        });

        const footerRow = `
            <tr class="table-active">
                <td colspan="4" class="text-right font-weight-bold">CUSTO TOTAL DOS COMPONENTES:</td>
                <td class="text-center font-weight-bold text-primary">${formatCurrency(totalCost)}</td>
                <td></td>
            </tr>
        `;
        tableFoot.append(footerRow);
    };

    const handleAddComponent = () => {
        const selectedComponent = $('#componentSearch').select2('data')[0];
        const quantity = parseFloat($('#componentQuantity').val());

        if (!selectedComponent || !selectedComponent.id) {
            alert('Selecione um componente.');
            return;
        }
        if (isNaN(quantity) || quantity <= 0) {
            alert('Informe uma quantidade válida.');
            return;
        }
        if (selectedComponent.id === config.produtoId) {
            alert('Um produto não pode ser seu próprio componente.');
            return;
        }
        if (bomState.some(c => c.component_id === selectedComponent.id)) {
            alert('Este componente já foi adicionado.');
            return;
        }

        const componentData = {
            componente_id: selectedComponent.id,
            quantidade: quantity
        };

        $.ajax({
            url: config.bomUrl,
            method: 'POST',
            data: componentData,
            success: () => {
                bomState.push({
                    component_id: selectedComponent.id,
                    sku: selectedComponent.sku,
                    name: selectedComponent.name,
                    quantity: quantity,
                    cost: selectedComponent.cost
                });
                renderBomTable();
                $('#componentSearch').val(null).trigger('change');
                $('#componentQuantity').val('');
            },
            error: (err) => {
                console.error("Erro ao adicionar componente:", err);
                alert(err.responseJSON?.error || 'Falha ao adicionar componente.');
            }
        });
    };

    const handleRemoveComponent = (event) => {
        const componentId = $(event.currentTarget).data('component-id');
        
        if (!confirm('Tem certeza que deseja remover este componente?')) {
            return;
        }

        $.ajax({
            url: `${config.bomUrl}?componente_id=${componentId}`,
            method: 'DELETE',
            success: () => {
                bomState = bomState.filter(c => c.component_id !== componentId);
                renderBomTable();
            },
            error: (err) => {
                console.error("Erro ao remover componente:", err);
                alert(err.responseJSON?.error || 'Falha ao remover componente.');
            }
        });
    };

    const handleApplyTemplate = (event) => {
        const templateId = $(event.currentTarget).data('template-id');
        const url = config.applyTemplateUrl.replace('TEMPLATE_ID', templateId);

        if (!confirm('Isso substituirá a lista de componentes atual. Deseja continuar?')) {
            return;
        }

        $.ajax({
            url: url,
            method: 'POST',
            success: () => {
                $('#applyTemplateModal').modal('hide');
                loadInitialBom(); // Recarrega a lista de componentes
            },
            error: (err) => {
                console.error("Erro ao aplicar template:", err);
                alert(err.responseJSON?.error || 'Falha ao aplicar o template.');
            }
        });
    };

    const initComponentSearch = () => {
        $('#componentSearch').select2({
            placeholder: 'Buscar componente por SKU ou nome...', // Corrected placeholder
            minimumInputLength: 2,
            ajax: {
                url: config.searchUrl,
                dataType: 'json',
                delay: 250,
                data: (params) => ({
                    q: params.term,
                    exclude_id: config.produtoId
                }),
                processResults: (data) => ({
                    results: data.results.map(item => ({
                        id: item.id,
                        text: item.text,
                        sku: item.sku,
                        name: item.name,
                        cost: item.cost
                    }))
                }),
                cache: true
            }
        });
    };

    const formatCurrency = (value) => {
        return (value || 0).toLocaleString('pt-BR', {
            style: 'currency',
            currency: 'BRL',
            minimumFractionDigits: 2,
            maximumFractionDigits: 4
        });
    };

    return {
        init
    };
})();
