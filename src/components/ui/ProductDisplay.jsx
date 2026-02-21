import React from 'react';

const ProductDisplay = ({ product, productId = null }) => {
  // Se o produto for fornecido diretamente, usamos seus dados
  if (product) {
    return (
      <div className="font-medium">
        <div className="font-medium">
          {product.nome || product.name || `Produto ID: ${product.id || productId}`}
        </div>
        <div className="text-sm text-muted-foreground">
          SKU: {product.sku || product.sku_mestre || 'N/A'}
        </div>
      </div>
    );
  }

  // Se apenas o ID for fornecido, mostramos o ID
  return (
    <div className="font-medium">
      <div className="font-medium">
        {`Produto ID: ${productId}`}
      </div>
      <div className="text-sm text-muted-foreground">
        SKU: N/A
      </div>
    </div>
  );
};

export default ProductDisplay;