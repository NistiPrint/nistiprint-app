"""Pure grouping rules for PDFs associated with finished products."""

from decimal import Decimal


def build_print_groups(product_id, arts, components, legacy_groups):
    if not arts:
        return legacy_groups
    groups = []
    covered = set()
    for art in arts:
        links = [link for link in art["componentes"] if link["papel"] in ("capa", "contra")]
        if not links:
            continue
        ids = [int(link["componente_id"]) for link in links]
        covered.update(ids)
        quantities = [components[component_id]["quantidade"] for component_id in ids if component_id in components]
        error = None
        if any(link["papel"] == "miolo" for link in art["componentes"]):
            error = "Esta arte também inclui miolo; a impressão conjunta será liberada quando o fluxo de miolo estiver disponível"
        elif len(quantities) != len(ids):
            error = "A ficha de materiais mudou; revise os componentes desta arte"
        elif len(set(quantities)) != 1:
            error = "Os componentes desta arte exigem quantidades diferentes por produto"
        groups.append({
            "produto_capa_id": ids[0], "sku_capa": f"arte:{art['id']}",
            "capa_nome": art["nome"], "quantidade_por_unidade": float(quantities[0]) if quantities else 0,
            "arte_id": art["id"], "produto_final_id": int(product_id),
            "componentes_ids": ids, "papeis": [link["papel"] for link in links], "pendencia_arte": error,
        })
    for component_id, component in components.items():
        if component["papel_sugerido"] not in ("capa", "contra") or component_id in covered:
            continue
        groups.append({
            "produto_capa_id": component_id, "sku_capa": component["sku"],
            "capa_nome": component["nome"], "quantidade_por_unidade": float(component["quantidade"]),
            "arte_id": None, "produto_final_id": int(product_id),
            "componentes_ids": [component_id], "papeis": [component["papel_sugerido"]],
            "pendencia_arte": "Componente sem arte vinculada no produto final",
        })
    return groups


def legacy_credit(component_ids, artwork_id, planned, owners, confirmations, active_groups):
    """Return confirmed copies and whether ambiguous old work needs review."""
    old_keys = [f"{component_id}|estatica" for component_id in component_ids]
    values = [Decimal(str(confirmations.get(key) or 0)) for key in old_keys]
    active = any(value > 0 for value in values) or any(key in active_groups for key in old_keys)
    if not active:
        return Decimal(0), False
    safe = (len(set(values)) == 1 and values[0] > 0 and values[0] <= planned
            and all(owners.get(component_id) == {artwork_id} for component_id in component_ids))
    return (values[0], False) if safe else (Decimal(0), True)
