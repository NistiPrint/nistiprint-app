import React, { useState, useEffect } from 'react';
import ProductService from '../../services/ProductService';
import { Input } from './input';
import { Search, X } from 'lucide-react';
import { Button } from './button';
import { Badge } from './badge';

const ProductSelector = ({ value, onChange, placeholder = "Selecione um produto", disabled = false }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState(null);

  // Atualiza o estado quando o valor externo muda
  useEffect(() => {
    if (value && !selectedProduct) {
      // Carrega os dados do produto existente
      const fetchProduct = async () => {
        try {
          const product = await ProductService.getById(parseInt(value));
          if (product) {
            setSelectedProduct(product);
            setSearchTerm(product.name);
          }
        } catch (error) {
          console.error("Error fetching product:", error);
        }
      };
      fetchProduct();
    } else if (!value && selectedProduct) {
      setSelectedProduct(null);
      setSearchTerm('');
    }
  }, [value]);

  // Debounce search
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if (searchTerm.length >= 3 && !selectedProduct) {
        performSearch(searchTerm);
      } else if (searchTerm.length < 3) {
        setSearchResults([]);
      }
    }, 500);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm, selectedProduct]);

  const performSearch = async (value) => {
    setIsSearching(true);
    try {
      const results = await ProductService.search(value, {});
      setSearchResults(results.results || []);
    } catch (error) {
      console.error("Error searching products:", error);
    } finally {
      setIsSearching(false);
    }
  };

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchTerm(value);

    // If user is typing again, deselect the previously selected product
    if (selectedProduct && value !== selectedProduct.name) {
      setSelectedProduct(null);
      onChange(null); // Limpa o valor quando o texto muda
    }
  };

  const selectProduct = (product) => {
    setSelectedProduct(product);
    setSearchTerm(product.name);
    setSearchResults([]);
    onChange(product.id);
  };

  const removeSelection = () => {
    setSelectedProduct(null);
    setSearchTerm('');
    setSearchResults([]);
    onChange(null);
  };

  return (
    <div className="relative w-full">
      <div className="relative">
        <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={placeholder}
          value={searchTerm}
          onChange={handleSearchChange}
          className="pl-8"
          disabled={disabled}
        />
        {selectedProduct && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="absolute right-2 top-1.5 h-6 w-6 p-0"
            onClick={removeSelection}
            disabled={disabled}
          >
            <X className="h-3 w-3" />
          </Button>
        )}
        {isSearching && (
          <div className="absolute right-8 top-2.5">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
          </div>
        )}
      </div>
      
      {searchTerm.length >= 3 && !selectedProduct && !isSearching && searchResults.length === 0 && (
        <div className="absolute z-10 w-full bg-popover border rounded-md shadow-md mt-1 p-3 text-sm text-muted-foreground">
          Nenhum produto encontrado.
        </div>
      )}
      
      {searchResults.length > 0 && (
        <div className="absolute z-10 w-full bg-popover border rounded-md shadow-md mt-1 max-h-60 overflow-auto">
          {searchResults.map(product => (
            <div
              key={product.id}
              className="p-2 hover:bg-accent cursor-pointer text-sm"
              onClick={() => selectProduct(product)}
            >
              <div className="font-medium">{product.name}</div>
              <div className="text-xs text-muted-foreground">
                {product.sku} - R$ {product.cost}
                {product.material_type && (
                  <span className="ml-2">
                    <Badge variant="secondary" className="text-xs">
                      {product.material_type}
                    </Badge>
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      
      {selectedProduct && (
        <div className="mt-2 p-2 bg-secondary rounded-md text-sm">
          <div className="font-medium">{selectedProduct.name}</div>
          <div className="text-xs text-muted-foreground">
            {selectedProduct.sku} - R$ {selectedProduct.cost}
            {selectedProduct.material_type && (
              <span className="ml-2">
                <Badge variant="secondary" className="text-xs">
                  {selectedProduct.material_type}
                </Badge>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductSelector;