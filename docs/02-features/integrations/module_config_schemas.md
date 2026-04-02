# Esquema mínimo de `config` por `module_id` (installed_integrations)

O vínculo **cross-module** (qual instância Bling + qual instância de marketplace corresponde a qual `bling_loja_id`) fica centralizado em `integracao_canais_config`, não duplicado no JSON de cada módulo.

## `bling`

- **Obrigatório**: credenciais OAuth / tokens na estrutura já usada pela instalação (`credentials`, `access_token`, etc.).
- **Opcional**: `cnpj`, metadados de conta.

## `shopee` (e análogos: `amazon`, `mercadolivre`, `shein`)

- **Obrigatório**: credenciais da API do marketplace conforme o conector.
- **Opcional**: `shop_id`, região, flags de ambiente — apenas o que a integração daquele módulo exige.

## Uso em runtime

- Ao processar um pedido vindo do Bling, use `loja.id` → busca em `integracao_canais_config.bling_loja_id` para obter `bling_integration_id` (token/API Bling) e `marketplace_integration_id` (enriquecimento Shopee etc.).
