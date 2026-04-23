// static/js/composition_template_form.js
document.addEventListener('DOMContentLoaded', function() {
    const pathParts = window.location.pathname.split('/');
    const templateId = pathParts[pathParts.indexOf('editar') - 1];
    const componentSearchInput = $('#component-search'); // Use jQuery for Select2
    const componentQuantityInput = document.getElementById('component-quantity');
    const addComponentBtn = document.getElementById('add-component-btn');
    const templateItemsTableBody = document.querySelector('#template-items-table tbody');

    let selectedComponent = null; // To store the product selected from search

    // Initialize Select2 for component search
    componentSearchInput.select2({
        placeholder: "Buscar produto por nome ou SKU...",
        allowClear: true,
        minimumInputLength: 3,
        ajax: {
            url: "/produtos/api/search",
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    q: params.term, // search term
                    limit: 10
                };
            },
            processResults: function (data) {
                return {
                    results: data.results.map(function(product) {
                        return {
                            id: product.id,
                            text: `${product.name} (${product.sku})`,
                            product_data: {
                                id: product.id,
                                name: product.name,
                                sku: product.sku,
                                cost: product.cost
                            } // Store full product data
                        };
                    })
                };
            },
            cache: true
        }
    });

    componentSearchInput.on('select2:select', function (e) {
        selectedComponent = e.params.data.product_data;
        componentQuantityInput.focus();
    });

    componentSearchInput.on('select2:unselect', function (e) {
        selectedComponent = null;
    });