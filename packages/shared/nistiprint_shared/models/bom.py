# models/bom.py

class BOM:
    """
    Representa a Ficha Técnica (Bill of Materials) de um produto.
    Define os componentes e suas quantidades para produzir uma unidade de um produto pai.
    """
    def __init__(self, id, produto_pai_id, componente_id, quantidade, unidade_medida='un'):
        self.id = id
        self.produto_pai_id = produto_pai_id
        self.componente_id = componente_id
        self.quantidade = quantidade
        self.unidade_medida = unidade_medida

    def to_dict(self):
        return {
            "id": self.id,
            "produto_pai_id": self.produto_pai_id,
            "componente_id": self.componente_id,
            "quantidade": self.quantidade,
            "unidade_medida": self.unidade_medida
        }

class BOMItem:
    """
    Representa um item componente dentro de uma Ficha Técnica (BOM).
    """
    def __init__(self, componente_id, quantidade, unit='un', is_inherited=False, grupo=None):
        self.componente_id = componente_id
        self.quantidade = quantidade
        self.unit = unit
        # Verdadeiro quando a linha vem da ficha do produto PAI. É por linha, e
        # não por produto: numa ficha mesclada convivem linhas herdadas e linhas
        # próprias, e é isso que diz à tela o que pode ser editado.
        self.is_inherited = is_inherited
        # Grupo efetivo da linha (MIOLO, CAPA, CONTRA, ACABAMENTO, EMBALAGEM),
        # resolvido pelo banco em `grupo_bom_do_componente`.
        self.grupo = grupo

    def to_dict(self):
        return {
            "componente_id": self.componente_id,
            "quantidade": self.quantidade,
            "unit": self.unit,
            "is_inherited": self.is_inherited,
            "grupo": self.grupo
        }
