document.addEventListener('DOMContentLoaded', function() {
    const searchForm = document.getElementById('search-form');
    const resultsTableBody = document.querySelector('#results-table tbody');
    const bulkAssociateForm = document.getElementById('bulk-associate-form');
    const componentId = document.querySelector('input[name="component_id"]').value;

    // Function to fetch and render search results
    async function fetchAndRenderProducts(event) {
        event.preventDefault();
        const formData = new FormData(searchForm);
        const queryParams = new URLSearchParams(formData).toString();

        try {
            const response = await fetch(`/produtos/search_for_bom?${queryParams}`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const products = await response.json();
            renderProductResults(products);
        } catch (error) {
            console.error('Erro ao buscar produtos:', error);
            alert('Erro ao buscar produtos. Verifique o console para mais detalhes.');
        }
    }

    // Function to render products into the table
    function renderProductResults(products) {
        resultsTableBody.innerHTML = ''; // Clear previous results
        if (products.length === 0) {
            resultsTableBody.innerHTML = '<tr><td colspan="3" class="text-center">Nenhum produto encontrado.</td></tr>';
            return;
        }

        products.forEach(product => {
            const row = resultsTableBody.insertRow();
            row.innerHTML = `
                <td>${product.name}</td>
                <td>${product.sku}</td>
                <td>
                    <input type="number" class="form-control form-control-sm quantity-input" 
                           data-product-id="${product.id}" 
                           min="0" value="0">
                </td>
            `;
        });
    }

    // Function to handle bulk association save
    async function saveBulkAssociation(event) {
        event.preventDefault();

        const associations = [];
        document.querySelectorAll('.quantity-input').forEach(input => {
            const quantity = parseFloat(input.value);
            if (quantity > 0) {
                associations.push({
                    product_id: input.dataset.productId,
                    quantity: quantity
                });
            }
        });

        if (associations.length === 0) {
            alert('Nenhum produto selecionado ou quantidade maior que zero.');
            return;
        }

        try {
            const response = await fetch(`/produtos/${componentId}/associate_in_bulk`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ associations: associations })
            });

            const result = await response.json();

            if (response.ok) {
                alert(result.message || 'Associação em massa realizada com sucesso!');
                // Optionally clear the form or refresh results
                resultsTableBody.innerHTML = ''; // Clear results after successful save
                searchForm.reset(); // Reset search form
            } else {
                throw new Error(result.error || 'Erro desconhecido ao associar em massa.');
            }
        } catch (error) {
            console.error('Erro ao salvar associação em massa:', error);
            alert(`Erro ao salvar associação em massa: ${error.message}`);
        }
    }

    // Event Listeners
    searchForm.addEventListener('submit', fetchAndRenderProducts);
    bulkAssociateForm.addEventListener('submit', saveBulkAssociation);

    // Initial load (optional: if you want to show all products by default)
    // searchForm.dispatchEvent(new Event('submit')); 
});