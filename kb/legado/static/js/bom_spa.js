/**
 * Single Page Application - Gestão de Bill of Materials (BOM)
 * Versão simplificada e funcional
 */

class BOMSPA {
    constructor(productId) {
        this.productId = productId;
        this.selectedProductId = null;
        this.searchTimeout = null;
        this.initializeElements();
        this.bindEvents();
        if (!isNaN(this.productId)) {
            this.loadComponents();
        }
    }

    initializeElements() {
        this.productSearch = document.getElementById('productSearch');
        this.componentQuantity = document.getElementById('componentQuantity');
        this.addComponentBtn = document.getElementById('addComponentBtn');
        this.searchResults = document.getElementById('searchResults');
        this.componentsTable = document.getElementById('componentsTable');
    }

    bindEvents() {
        if (this.productSearch) {
            this.productSearch.addEventListener('input', this.debouncedSearch.bind(this));
        }
        if (this.addComponentBtn) {
            this.addComponentBtn.addEventListener('click', this.addComponent.bind(this));
        }
        if (this.componentQuantity) {
            this.componentQuantity.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.addComponent();
            });
        }

        // Limpar busca ao clicar fora
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.input-group')) {
                this.clearSearch();
            }
        });
    }

    debouncedSearch() {
        clearTimeout(this.searchTimeout);
        const query = this.productSearch.value.trim();

        if (query.length < 2) {
            this.searchResults.style.display = 'none';
            return;
        }

        this.searchTimeout = setTimeout(() => this.performSearch(query), 300);
    }

    performSearch(query) {
        if (isNaN(this.productId)) return;

        const exclude = this.productId;
        fetch(`/api/products/search?q=${encodeURIComponent(query)}&exclude=${exclude}`)
            .then(response => response.json())
            .then(products => {
                this.renderSearchResults(products);
                this.searchResults.style.display = products.length > 0 ? 'block' : 'none';
            })
            .catch(error => {
                console.error('Erro na busca:', error);
                this.showNotification('Erro na busca, tente novamente', 'error');
            });
    }

    renderSearchResults(products) {
        if (products.length === 0) {
            this.searchResults.innerHTML = `<div class="text-center text-muted p-2">Nenhum produto encontrado</div>`;
            return;
        }

        this.searchResults.innerHTML = products.map(product => `
            <div class="search-result-item" onclick="bomSPA.selectProduct(${product.id}, '${product.name.replace(/'/g, '\\\'')}', '${product.sku}')">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${product.name}</strong><br>
                        <code class="text-muted">${product.sku}</code>
                    </div>
                    <small class="text-success">R$ ${product.cost_price}</small>
                </div>
            </div>
        `).join('');
    }

    selectProduct(productId, name, sku) {
        this.selectedProductId = productId;
        this.productSearch.value = `${name} (${sku})`;
        this.clearSearch();
        this.componentQuantity.focus();
    }

    clearSearch() {
        this.searchResults.style.display = 'none';
    }

    addComponent() {
        const productId = this.selectedProductId;
        const quantity = parseFloat(this.componentQuantity.value);

        if (!productId) {
            this.showNotification('Selecione um produto primeiro', 'warning');
            return;
        }

        if (!quantity || quantity <= 0) {
            this.showNotification('Quantidade deve ser maior que zero', 'warning');
            return;
        }

        this.addComponentBtn.disabled = true;
        this.addComponentBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        fetch(`/api/products/${this.productId}/components`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ component_product_id: productId, quantity: quantity })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showNotification('Componente adicionado!', 'success');
                this.resetForm();
                this.loadComponents();
            } else {
                this.showNotification(data.error, 'error');
            }
        })
        .catch(error => {
            console.error('Erro:', error);
            this.showNotification('Erro na conexão', 'error');
        })
        .finally(() => {
            this.addComponentBtn.disabled = false;
            this.addComponentBtn.innerHTML = '<i class="fas fa-plus"></i> Adicionar';
        });
    }

    loadComponents() {
        fetch(`/api/products/${this.productId}/components`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.renderComponents(data.components);
                    this.updateTotalCost(data.product.total_cost);
                } else {
                    this.showNotification('Erro ao carregar componentes', 'error');
                }
            })
            .catch(error => {
                console.error('Erro ao carregar:', error);
            });
    }

    renderComponents(components) {
        const count = components.length;
        document.getElementById('componentCount').textContent = count;

        if (count === 0) {
            this.componentsTable.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="fas fa-cube fa-3x mb-3"></i>
                    <p>Nenhum componente adicionado ainda.</p>
                </div>
            `;
            return;
        }

        this.componentsTable.innerHTML = `
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>Produto</th>
                        <th>SKU</th>
                        <th>Quantidade</th>
                        <th>Custo Unitário</th>
                        <th>Custo Total</th>
                        <th>Ações</th>
                    </tr>
                </thead>
                <tbody>
                    ${components.map(comp => `
                        <tr>
                            <td><strong>${comp.component_product_name}</strong></td>
                            <td><code>${comp.component_product_sku}</code></td>
                            <td>
                                <input type="number" class="form-control-sm" step="0.01" min="0.01"
                                       value="${comp.quantity}" style="width: 80px"
                                       onchange="bomSPA.updateQuantity(${comp.id}, this.value)">
                            </td>
                            <td>R$ ${comp.component_product.cost_price.toFixed(2)}</td>
                            <td>R$ ${(comp.component_product.cost_price * comp.quantity).toFixed(2)}</td>
                            <td>
                                <button class="btn btn-sm btn-outline-danger"
                                        onclick="bomSPA.removeComponent(${comp.id}, '${comp.component_product_name}')">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }

    updateQuantity(componentId, quantity) {
        fetch(`/api/products/components/${componentId}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ quantity: parseFloat(quantity) })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showNotification('Quantidade atualizada!', 'success');
                this.loadComponents();
            } else {
                this.showNotification(data.error, 'error');
            }
        })
        .catch(error => {
            this.showNotification('Erro na atualização', 'error');
        });
    }

    removeComponent(componentId, name) {
        if (confirm(`Remover "${name}" desta composição?`)) {
            fetch(`/api/products/components/${componentId}`, {
                method: 'DELETE'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.showNotification('Componente removido!', 'success');
                    this.loadComponents();
                } else {
                    this.showNotification(data.error, 'error');
                }
            })
            .catch(error => {
                this.showNotification('Erro na remoção', 'error');
            });
        }
    }

    async applyTemplate(templateId, templateName) {
        if (!this.productId) {
            this.showNotification('Salve o produto primeiro antes de aplicar templates.', 'warning');
            return;
        }

        if (confirm(`Aplicar template "${templateName}" a este produto? Os componentes serão adicionados à lista atual.`)) {
            try {
                const response = await fetch(`/templates/composition/apply/${templateId}/to_product/${this.productId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ overwrite_existing: false }) // Option to overwrite or just add
                });
                const result = await response.json();

                if (response.ok) {
                    // Close the modal
                    $('#applyTemplateModal').modal('hide');
                    this.showNotification(result.message || `Componentes do template "${templateName}" aplicados com sucesso!`, 'success');
                    this.loadComponents(); // Reload BOM to show new components
                    // Assuming calcularCustos is a global function or part of BOMSPA
                    if (typeof calcularCustos === 'function') {
                        setTimeout(calcularCustos, 500);
                    }
                } else {
                    throw new Error(result.error || 'Erro desconhecido ao aplicar template.');
                }
            } catch (error) {
                console.error('Erro ao aplicar template:', error);
                this.showNotification(`Erro ao aplicar template: ${error.message}`, 'error');
            }
        }
    }

    updateTotalCost(cost) {
        document.getElementById('totalCost').textContent = `R$ ${parseFloat(cost).toFixed(4)}`;
    }

    resetForm() {
        if (this.productSearch) this.productSearch.value = '';
        if (this.componentQuantity) this.componentQuantity.value = '';
        this.selectedProductId = null;
        this.clearSearch();
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = `
            top: 20px; right: 20px; min-width: 300px;
            max-width: 500px; z-index: 9999; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        `;

        const iconMap = {
            'success': 'check-circle',
            'error': 'exclamation-triangle',
            'warning': 'exclamation-circle',
            'info': 'info-circle'
        };

        notification.innerHTML = `
            <button type="button" class="close" data-dismiss="alert">
                <span>&times;</span>
            </button>
            <i class="fas fa-${iconMap[type]} mr-2"></i> ${message}
        `;

        document.body.appendChild(notification);

        if (type === 'success') {
            setTimeout(() => notification.remove(), 5000);
        }
    }
}

// Inicialização global
let bomSPA;
document.addEventListener('DOMContentLoaded', () => {
    const productId = window.productId || parseInt(window.location.pathname.split('/').pop(), 10);
    if (productId && !isNaN(productId)) {
        bomSPA = new BOMSPA(productId);
    }
});
