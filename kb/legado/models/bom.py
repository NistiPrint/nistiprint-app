# models/bom.py

class BOM:
    """
    Representa a Ficha Técnica (Bill of Materials) de um produto.
    Define os componentes e suas quantidades para produzir uma unidade de um produto pai.
    """
    def __init__(self, id, produto_pai_id, componente_id, quantidade):
        self.id = id
        self.produto_pai_id = produto_pai_id
        self.componente_id = componente_id
        self.quantidade = quantidade

    def to_dict(self):
        return {
            "id": self.id,
            "produto_pai_id": self.produto_pai_id,
            "componente_id": self.componente_id,
            "quantidade": self.quantidade
        }

class BOMItem:
    """
    Representa um item componente dentro de uma Ficha Técnica (BOM).
    """
    def __init__(self, componente_id, quantidade):
        self.componente_id = componente_id
        self.quantidade = quantidade

    def to_dict(self):
        return {
            "componente_id": self.componente_id,
            "quantidade": self.quantidade
        }