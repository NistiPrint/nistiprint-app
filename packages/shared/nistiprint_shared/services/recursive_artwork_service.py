"""Resolve produtos que podem possuir artes dentro de uma ficha técnica."""

from typing import Any

class RecursiveArtworkService:
    MAX_DEPTH = 20

    def list_for_product(self, product_id: str) -> list[dict[str, Any]]:
        from nistiprint_shared.services.bom_service import bom_service
        self.bom_service = bom_service
        result: dict[str, dict[str, Any]] = {}
        self._walk(str(product_id), [str(product_id)], 0, 1, result)
        return list(result.values())

    def _walk(self, parent_id: str, path: list[str], depth: int, quantity: float, result: dict):
        if depth >= self.MAX_DEPTH:
            return
        from nistiprint_shared.services.category_service import category_service
        from nistiprint_shared.services.product_service import product_service
        for component in self.bom_service.get_bom_for_produto(int(parent_id)):
            component_id = str(component.componente_id)
            if component_id in path:
                continue
            product = product_service.get_by_id(component_id)
            if not product:
                continue
            category = category_service.get_by_id(str(product.get('categoria_id'))) if product.get('categoria_id') else None
            total_quantity = quantity * float(component.quantidade or 1)
            if category and category.get('permite_arte'):
                existing = result.get(component_id)
                if existing:
                    existing['quantity'] += total_quantity
                else:
                    result[component_id] = {
                        'product_id': component_id,
                        'sku': product.get('sku'),
                        'name': product.get('nome') or product.get('name'),
                        'category_id': product.get('categoria_id'),
                        'category_name': category.get('nome'),
                        'permite_arte': True,
                        'depth': depth + 1,
                        'bom_path': path + [component_id],
                        'quantity': total_quantity,
                    }
            self._walk(component_id, path + [component_id], depth + 1, total_quantity, result)


recursive_artwork_service = RecursiveArtworkService()