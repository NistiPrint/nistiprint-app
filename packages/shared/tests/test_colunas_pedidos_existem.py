"""Guarda contra referencia a coluna inexistente em `pedidos`.

Este teste existe por causa de um incidente concreto: em 02/08/2026 as colunas
`bling_integration_id`, `bling_loja_id`, `bling_order_id`, `bling_order_number` e
`shop_id_shopee` foram removidas de `pedidos` (duplicavam as `erp_*`, com zero
divergencia em 7.176 linhas). O `DROP` passou limpo, mas quatro objetos de banco
e sete pontos de codigo continuavam referenciando as colunas.

O Postgres nao valida corpo de funcao plpgsql no `DROP`, e o PostgREST so
reclama na chamada. Resultado: o ingest caiu, e cada ponto quebrado apareceu um
de cada vez, em producao, ao longo de meia hora.

## Por que AST e nao grep

A primeira versao deste teste procurava o nome da coluna numa janela de texto
depois de `.table("pedidos")`. Deu quatro falsos positivos: os mesmos nomes
existem legitimamente em `channel_connections.bling_integration_id` e em
variaveis locais, e uma janela de N caracteres nao distingue "argumento desta
query" de "linha que por acaso esta perto".

A analise sintatica sabe a diferenca: percorre a cadeia
`supabase_db.table("pedidos").select(...).eq(...)` e olha apenas os literais
que sao argumento dela.
"""
import ast
import pathlib
import unittest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Colunas removidas em 02/08/2026. O nome pode aparecer legitimamente em OUTRAS
#: tabelas (`channel_connections.bling_integration_id`, `pedidos_bling.bling_id`)
#: e como parametro de API — por isso a checagem e por cadeia de chamada.
COLUNAS_REMOVIDAS = (
    "bling_integration_id",
    "bling_loja_id",
    "bling_order_id",
    "bling_order_number",
    "shop_id_shopee",
)

DIRETORIOS = ("apps/api", "apps/worker", "packages/shared/nistiprint_shared", "scripts")
IGNORAR = ("__pycache__", "node_modules", ".venv", "build", "migrations")

#: Metodos cujo argumento nomeia coluna.
METODOS_COM_COLUNA = {
    "select", "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike",
    "is_", "in_", "order", "not_", "filter", "on_conflict", "or_",
}


def _arquivos_python():
    for base in DIRETORIOS:
        raiz = RAIZ / base
        if not raiz.exists():
            continue
        for caminho in raiz.rglob("*.py"):
            if any(parte in str(caminho) for parte in IGNORAR):
                continue
            yield caminho


def _e_tabela_pedidos(no: ast.AST) -> bool:
    """`...table("pedidos")` em qualquer ponto da cadeia."""
    atual = no
    while isinstance(atual, ast.Call):
        func = atual.func
        if isinstance(func, ast.Attribute):
            if func.attr == "table" and atual.args:
                arg = atual.args[0]
                if isinstance(arg, ast.Constant) and arg.value == "pedidos":
                    return True
            atual = func.value
        else:
            break
    return False


def _literais_da_cadeia(no: ast.Call):
    """Literais de string passados a metodos de coluna e chaves de update."""
    atual = no
    while isinstance(atual, ast.Call):
        func = atual.func
        if isinstance(func, ast.Attribute):
            if func.attr in METODOS_COM_COLUNA:
                for arg in atual.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        yield arg.value
            if func.attr in ("update", "insert", "upsert"):
                for arg in atual.args:
                    if isinstance(arg, ast.Dict):
                        for chave in arg.keys:
                            if isinstance(chave, ast.Constant) and isinstance(chave.value, str):
                                yield chave.value
            atual = func.value
        else:
            break


class TestColunasPedidos(unittest.TestCase):
    def test_nenhuma_query_em_pedidos_usa_coluna_removida(self):
        infracoes = []
        for caminho in _arquivos_python():
            texto = caminho.read_text(encoding="utf-8", errors="ignore")
            try:
                arvore = ast.parse(texto)
            except SyntaxError:
                # O sandbox roda 3.10 e producao roda 3.12; sintaxe mais nova
                # nao parseia aqui. Pular e melhor que falhar por engano — a
                # cobertura real acontece no CI, na versao certa.
                continue

            for no in ast.walk(arvore):
                if not isinstance(no, ast.Call) or not _e_tabela_pedidos(no):
                    continue
                for literal in _literais_da_cadeia(no):
                    for coluna in COLUNAS_REMOVIDAS:
                        if coluna in literal:
                            infracoes.append(
                                f"{caminho.relative_to(RAIZ)}:{no.lineno} usa "
                                f"'{coluna}' em query de `pedidos`"
                            )

        self.assertEqual(
            [],
            sorted(set(infracoes)),
            "Colunas removidas de `pedidos` ainda referenciadas:\n  - "
            + "\n  - ".join(sorted(set(infracoes)))
            + "\n\nUse as canonicas: erp_integration_id, erp_store_id, "
            "erp_order_id, erp_order_number, marketplace_integration_id.",
        )

    def test_a_varredura_cobre_o_repositorio(self):
        """Guarda do guarda: um filtro quebrado tornaria o teste inutil."""
        self.assertGreater(
            sum(1 for _ in _arquivos_python()), 100,
            "varredura encontrou poucos arquivos demais",
        )

    def test_detecta_uma_infracao_plantada(self):
        """O teste precisa saber reprovar, nao so aprovar."""
        codigo = 'supabase_db.table("pedidos").select("id,bling_loja_id").execute()'
        no = next(
            n for n in ast.walk(ast.parse(codigo))
            if isinstance(n, ast.Call) and _e_tabela_pedidos(n)
        )
        self.assertIn("id,bling_loja_id", list(_literais_da_cadeia(no)))

    def test_nao_confunde_outra_tabela(self):
        """`channel_connections.bling_integration_id` e legitimo."""
        codigo = 'supabase_db.table("channel_connections").select("bling_integration_id").execute()'
        achou = any(
            _e_tabela_pedidos(n)
            for n in ast.walk(ast.parse(codigo))
            if isinstance(n, ast.Call)
        )
        self.assertFalse(achou)


if __name__ == "__main__":
    unittest.main()
