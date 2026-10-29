import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import ProductService from '../../services/ProductService';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Search, X, Check } from 'lucide-react';
import { ProductLevelBadge } from '@/components/produtos/ProductLevelBadge';

/**
 * Componente de pesquisa de produtos reutilizável
 * @param {Object} props
 * @param {string} props.value - Valor atual do campo
 * @param {string} props.selectedProductId - ID do produto selecionado
 * @param {function} props.onChange - Callback quando o valor muda
 * @param {function} props.onProductSelect - Callback quando um produto é selecionado
 * @param {string} props.placeholder - Placeholder do input
 * @param {string} props.formato - Formato da busca ('kit', 'composicao', ou null)
 * @param {string} props.searchCategoryId - ID da categoria para filtrar
 * @param {boolean} props.onlyMarketable - Se deve buscar apenas produtos comercializáveis
 * @param {string} props.excludeId - ID do produto a excluir da busca
 * @param {string} props.className - Classe CSS adicional
 * @param {boolean} props.showProductLevelBadge - Se deve mostrar badge de tipo de material
 * @param {boolean} props.showCheckIndicator - Se deve mostrar indicador de produto selecionado
 */
const ProductSearchInput = ({
  value = '',
  selectedProductId = null,
  onChange,
  onProductSelect,
  placeholder = 'Digite para buscar...',
  formato = null,
  searchCategoryId = null,
  onlyMarketable = false,
  excludeId = null,
  className = '',
  showProductLevelBadge = true,
  showCheckIndicator = true,
  materialTypes = null,
}) => {
  const [searchTerm, setSearchTerm] = useState(value);
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState(null);
  const containerRef = useRef(null);

  // Debounce search
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if (searchTerm.length >= 3 || (searchTerm.length === 0 && searchCategoryId)) {
        performSearch(searchTerm);
      } else {
        setSearchResults([]);
        setShowDropdown(false);
      }
    }, 500);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm, searchCategoryId, formato, materialTypes]);

  // Sync with external value
  useEffect(() => {
    setSearchTerm(value);
  }, [value]);

  useLayoutEffect(() => {
    if (!showDropdown || !containerRef.current) return undefined;

    const updatePosition = () => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setDropdownStyle({
        position: 'fixed',
        left: rect.left,
        top: rect.bottom + 4,
        width: rect.width,
        zIndex: 1000,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [showDropdown, searchResults]);

  const performSearch = async (query) => {
    if (!query || query.length < 3) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }

    setIsSearching(true);
    try {
      // Determinar o contexto da busca
      let contexto = null;
      if (formato === 'kit') {
        contexto = 'kit';
      } else if (formato === 'composicao' && !materialTypes) {
        contexto = 'producao';
      }

      // Usar ProductService ou fallback para API direta
      let results;
      if (onlyMarketable) {
        // Fallback para API direta quando precisa de only_marketable
        const response = await fetch(`/api/v2/estoque/produtos-busca?q=${encodeURIComponent(query)}&only_marketable=true`);
        const data = await response.json();
        results = (data.results || []).map(item => ({
          id: item.id,
          name: item.text.split(' - ').slice(1).join(' - ') || item.text,
          sku: item.text.split(' - ')[0] || '',
          full_text: item.text,
        }));
      } else {
        const data = await ProductService.search(query, {
          exclude_id: excludeId,
          category_id: searchCategoryId,
          contexto: contexto,
          ...(materialTypes ? { material_type: materialTypes } : {}),
        });
        // Normalizar formato dos resultados
        results = (data.results || []).map(product => ({
          id: product.id,
          name: product.name,
          sku: product.sku || '',
          cost: product.cost,
          material_type: product.material_type || product.tipo_material || 'produto_acabado',
        }));
      }

      // Filtrar produto selecionado e excluídos
      const filtered = results.filter(p => 
        String(p.id) !== String(selectedProductId) &&
        String(p.id) !== String(excludeId) &&
        (!materialTypes || materialTypes.includes(p.material_type))
      );

      setSearchResults(filtered);
      setShowDropdown(filtered.length > 0);
    } catch (error) {
      console.error("Error searching products:", error);
      setSearchResults([]);
      setShowDropdown(false);
    } finally {
      setIsSearching(false);
    }
  };

  const handleInputChange = (e) => {
    const newValue = e.target.value;
    setSearchTerm(newValue);
    onChange?.(newValue);
  };

  const handleProductSelect = (product) => {
    setSearchTerm(product.name);
    setSearchResults([]);
    setShowDropdown(false);
    onProductSelect?.(product);
  };

  const clearSelection = () => {
    setSearchTerm('');
    setSearchResults([]);
    setShowDropdown(false);
    onChange?.('');
  };

  return (
    <div ref={containerRef} className={`relative w-full ${className}`}>
      <div className="relative">
        <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={placeholder}
          value={searchTerm}
          onChange={handleInputChange}
          onFocus={() => searchTerm.length >= 3 && setShowDropdown(true)}
          className="pl-8 pr-8"
        />
        {isSearching && (
          <div className="absolute right-2 top-2.5">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
          </div>
        )}
        {showCheckIndicator && selectedProductId && !isSearching && (
          <div className="absolute right-2 top-1/2 transform -translate-y-1/2 text-xs text-green-600 font-bold px-1 bg-green-100 rounded flex items-center gap-1">
            <Check className="h-3 w-3" />
            {searchCategoryId && (
              <X 
                className="h-3 w-3 cursor-pointer hover:text-red-600" 
                onClick={clearSelection}
              />
            )}
          </div>
        )}
      </div>

      {showDropdown && searchResults.length > 0 && dropdownStyle && createPortal(
        <div style={dropdownStyle} className="bg-popover border rounded-md shadow-md max-h-60 overflow-auto">
          <ScrollArea className="h-[200px]">
            <div className="p-1">
              {searchResults.map(product => (
                <div
                  key={product.id}
                  className="p-2 hover:bg-accent cursor-pointer text-sm rounded-sm"
                  onClick={() => handleProductSelect(product)}
                >
                  <div className="font-medium">{product.name}</div>
                  <div className="text-xs text-muted-foreground flex items-center gap-2">
                    <span>{product.sku}</span>
                    {showProductLevelBadge && product.material_type && (
                      <ProductLevelBadge type={product.material_type} />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>,
        document.body
      )}

      {searchTerm.length >= 3 && !isSearching && searchResults.length === 0 && showDropdown && dropdownStyle && createPortal(
        <div style={dropdownStyle} className="bg-popover border rounded-md shadow-md p-3 text-sm text-muted-foreground">
          Nenhum produto encontrado.
        </div>,
        document.body
      )}
    </div>
  );
};

export default ProductSearchInput;
