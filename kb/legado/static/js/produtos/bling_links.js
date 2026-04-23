$(document).ready(function() {
    // Use global variables passed from Jinja2
    const produtoId = currentProdutoId;
    let localBlingLinks = initialBlingLinks; // Initialize with existing links

    let blingAccounts = []; // To store fetched Bling accounts

    // Function to load Bling accounts into the select dropdown
    function loadBlingAccounts() {
        const select = $('#blingAccountSelect');
        // If the select is already disabled (meaning a default is set by Jinja), do not re-populate
        if (select.prop('disabled')) {
            console.log('Bling account select is disabled, skipping AJAX call for accounts.');
            return;
        }

        $.ajax({
            url: '/produtos/api/bling_accounts',
            method: 'GET',
            success: function(accounts) {
                console.log('Bling accounts fetched:', accounts); // Add this line
                blingAccounts = accounts;
                select.empty();
                select.append('<option value="">Selecione uma conta...</option>');
                accounts.forEach(account => {
                    select.append(`<option value="${account.id}">${account.account_name} (${account.cnpj})</option>`);
                });
                // Re-initialize Select2 after options are loaded
                select.select2({
                    placeholder: 'Selecione uma conta Bling',
                    allowClear: true,
                    dropdownParent: $('#addBlingLinkModal')
                });
            },
            error: function(xhr) {
                console.error('Erro ao carregar contas Bling:', xhr); // Add this line
                alert('Erro ao carregar contas Bling: ' + xhr.responseJSON.error);
            }
        });
    }

    // Function to render the local Bling links to the table
    function renderBlingLinksTable() {
        const tableBody = $('#bling-links-table-body');
        tableBody.empty(); // Clear existing rows

        if (localBlingLinks.length === 0) {
            $('#bling-links-table-body').parent().next('p.text-muted').show();
        } else {
            $('#bling-links-table-body').parent().next('p.text-muted').hide();
            localBlingLinks.forEach(link => {
                const newRow = `
                    <tr>
                        <td>${link.bling_product_id}</td>
                        <td>${link.bling_sku}</td>
                        <td>${link.bling_name || 'N/A'}</td>
                        <td>${link.bling_account_id}</td>
                        <td class="text-center">
                            <button type="button" class="btn btn-danger btn-sm remove-bling-link-btn" 
                                    data-bling-product-id="${link.bling_product_id}" 
                                    data-bling-account-id="${link.bling_account_id}">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>
                `;
                tableBody.append(newRow);
            });
        }
        // Update the hidden input field with the JSON representation of localBlingLinks
        $('#blingProductLinksJson').val(JSON.stringify(localBlingLinks));
    }

    // Initial render of the table
    renderBlingLinksTable();

    // Load accounts when the modal is shown
    $('#addBlingLinkModal').on('show.bs.modal', function () {
        loadBlingAccounts();
        // Clear previous selections/inputs only if the select is not disabled
        const blingAccountSelect = $('#blingAccountSelect');
        if (!blingAccountSelect.prop('disabled')) {
            blingAccountSelect.val('');
        }
        $('#modalBlingProductSearch').val(null).trigger('change');
        $('#manualBlingProductId').val('');
        $('#manualBlingProductDetails').hide().empty();
        $('#manualBlingSkuList').val('');
    });

    // Initialize Select2 for Bling product search within the modal
    $('#modalBlingProductSearch').select2({
        placeholder: 'Buscar produtos no Bling por nome ou SKU...', 
        minimumInputLength: 3,
        dropdownParent: $('#addBlingLinkModal'), // Important for modals
        ajax: {
            url: function (params) {
                const selectedAccountId = $('#blingAccountSelect').val();
                if (!selectedAccountId) {
                    return null; // Don't make request if no account is selected
                }
                return `/produtos/api/bling_products/search?q=${params.term}&account_id=${selectedAccountId}`;
            },
            dataType: 'json',
            delay: 250,
            processResults: function (data) {
                return {
                    results: $.map(data.results, function (item) {
                        return {
                            id: item.id,
                            text: `${item.sku} - ${item.name}`,
                            bling_sku: item.sku,
                            bling_name: item.name,
                            bling_account_id: item.account_id
                        };
                    })
                };
            },
            cache: true
        }
    });

    // Handle Add Selected Bling Product button click
    $('#addSelectedBlingProductBtn').on('click', function() {
        const selectedProduct = $('#modalBlingProductSearch').select2('data')[0];
        if (!selectedProduct) {
            alert('Selecione um produto do Bling para vincular.');
            return;
        }

        const blingProductId = selectedProduct.id;
        const blingSku = selectedProduct.bling_sku;
        const blingName = selectedProduct.bling_name;
        const blingAccountId = selectedProduct.bling_account_id;

        addBlingLinkToLocalArray(blingProductId, blingSku, blingName, blingAccountId);
        $('#modalBlingProductSearch').val(null).trigger('change'); // Clear search
    });

    // Handle Search Manual Bling Product ID button click
    $('#searchManualBlingProductIdBtn').on('click', function() {
        const manualId = $('#manualBlingProductId').val().trim();
        const selectedAccountId = $('#blingAccountSelect').val();

        if (!selectedAccountId) {
            alert('Selecione uma conta Bling primeiro.');
            return;
        }
        if (!manualId) {
            alert('Informe um ID do produto Bling.');
            return;
        }

        // Make an AJAX call to get product details from Bling
        $.ajax({
            url: `/produtos/api/bling_products/${manualId}?account_id=${selectedAccountId}`,
            method: 'GET',
            success: function(response) {
                if (response.success && response.product) {
                    const product = response.product;
                    const detailsHtml = `
                        <p><strong>ID:</strong> ${product.id}</p>
                        <p><strong>SKU:</strong> ${product.codigo}</p>
                        <p><strong>Nome:</strong> ${product.nome}</p>
                        <button type="button" class="btn btn-success btn-sm mt-2" 
                                id="confirmManualBlingProductBtn"
                                data-bling-product-id="${product.id}"
                                data-bling-sku="${product.codigo}"
                                data-bling-name="${product.nome}"
                                data-bling-account-id="${selectedAccountId}">
                            Confirmar Vínculo
                        </button>
                    `;
                    $('#manualBlingProductDetails').html(detailsHtml).show();
                } else {
                    $('#manualBlingProductDetails').html('Produto não encontrado ou erro ao buscar.').show();
                }
            },
            error: function(xhr) {
                $('#manualBlingProductDetails').html('Erro ao buscar produto: ' + xhr.responseJSON.error).show();
            }
        });
    });

    // Handle Confirm Manual Bling Product button click (delegated event)
    $(document).on('click', '#confirmManualBlingProductBtn', function() {
        const button = $(this);
        const blingProductId = button.data('bling-product-id');
        const blingSku = button.data('bling-sku');
        const blingName = button.data('bling-name');
        const blingAccountId = button.data('bling-account-id');

        addBlingLinkToLocalArray(blingProductId, blingSku, blingName, blingAccountId);
        $('#manualBlingProductId').val(''); // Clear input
        $('#manualBlingProductDetails').hide().empty(); // Hide details
    });

    // Handle Add Manual Bling SKU List button click
    $('#addManualBlingSkuListBtn').on('click', function() {
        const skuListText = $('#manualBlingSkuList').val().trim();
        const selectedAccountId = $('#blingAccountSelect').val();

        if (!selectedAccountId) {
            alert('Selecione uma conta Bling primeiro.');
            return;
        }
        if (!skuListText) {
            alert('Informe uma lista de SKUs.');
            return;
        }

        const skus = skuListText.split('\n').map(sku => sku.trim()).filter(sku => sku.length > 0);

        if (skus.length === 0) {
            alert('Nenhum SKU válido encontrado na lista.');
            return;
        }

        // Call the API to search for these SKUs in Bling
        $.ajax({
            url: `/produtos/api/bling_products/search_by_skus?skus=${skus.join(',')}&account_id=${selectedAccountId}`,
            method: 'GET',
            success: function(response) {
                const foundProducts = response.results || [];
                const foundSkus = new Set(foundProducts.map(p => p.sku));

                skus.forEach(sku => {
                    const foundProduct = foundProducts.find(p => p.sku === sku);
                    if (foundProduct) {
                        addBlingLinkToLocalArray(foundProduct.id, foundProduct.sku, foundProduct.name, selectedAccountId);
                    } else {
                        // If not found, add with SKU as ID and name
                        addBlingLinkToLocalArray(sku, sku, sku, selectedAccountId);
                    }
                });
                alert('Processamento da lista de SKUs concluído.');
                $('#manualBlingSkuList').val(''); // Clear input
            },
            error: function(xhr) {
                alert('Erro ao buscar SKUs no Bling: ' + xhr.responseJSON.error);
            }
        });
    });

    // Function to add a Bling link to the local array and re-render the table
    function addBlingLinkToLocalArray(blingProductId, blingSku, blingName, blingAccountId) {
        // Check for duplicates before adding
        const isDuplicate = localBlingLinks.some(link => 
            link.bling_product_id === blingProductId && 
            link.bling_account_id === blingAccountId
        );

        if (isDuplicate) {
            alert(`Vínculo para o produto Bling '${blingProductId}' na conta '${blingAccountId}' já existe.`);
            return;
        }

        localBlingLinks.push({
            bling_product_id: blingProductId,
            bling_sku: blingSku,
            bling_name: blingName,
            bling_account_id: blingAccountId
        });
        renderBlingLinksTable();
    }

    // Handle Remove Bling Link button click (delegated event for dynamically added buttons)
    $(document).on('click', '.remove-bling-link-btn', function() {
        const button = $(this);
        const blingProductId = button.data('bling-product-id');
        const blingAccountId = button.data('bling-account-id');

        if (confirm('Tem certeza que deseja remover este vínculo Bling?')) {
            localBlingLinks = localBlingLinks.filter(link => 
                !(link.bling_product_id === blingProductId && link.bling_account_id === blingAccountId)
            );
            renderBlingLinksTable();
        }
    });
});
