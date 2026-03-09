# Guia para Desenvolvimento de Módulos de Integração

Este guia explica como desenvolver um novo módulo de integração para torná-lo disponível para instalação no marketplace da aplicação.

## Visão Geral

O sistema de integração marketplace permite que usuários instalem módulos para conectar diferentes plataformas (como Shopee, Amazon, Mercado Livre, etc.) ao sistema. Cada módulo é uma entidade independente que define:

- Metadados (nome, descrição, versão, autor, etc.)
- Configuração necessária para a integração
- Fluxo de autenticação
- Especificações de mapeamento de dados

## Estrutura de um Módulo de Integração

Cada módulo de integração é definido como uma classe `IntegrationModule` com os seguintes campos:

- `name`: Nome do módulo
- `description`: Descrição detalhada
- `version`: Versão do módulo
- `author`: Autor do módulo
- `icon_url`: URL do ícone do módulo
- `category`: Categoria do módulo (ex: Marketplace, ERP, CRM)
- `tags`: Tags para facilitar a busca
- `is_active`: Indica se o módulo está ativo
- `config_schema`: Schema JSON para os campos de configuração
- `auth_flow`: Tipo de fluxo de autenticação (oauth2, api_key, basic_auth)
- `auth_config`: Configurações específicas para autenticação
- `data_mapping_spec`: Especificações para mapeamento de dados

## Passos para Desenvolver um Novo Módulo

### 1. Definir o Módulo

Crie uma função para definir seu módulo no arquivo `modules/platform_modules.py`:

```python
def get_nome_da_plataforma_module_definition():
    """Get the module definition for NomeDaPlataforma integration"""
    return IntegrationModule(
        name="NomeDaPlataforma Integration",
        description="Descrição da integração com NomeDaPlataforma",
        version="1.0.0",
        author="Seu Nome ou Equipe",
        icon_url="URL_para_o_ícone_da_plataforma",
        category="Marketplace",  # ou outra categoria apropriada
        tags=["nomedaplataforma", "e-commerce", "orders", "inventory"],
        auth_flow="oauth2",  # ou "api_key", "basic_auth"
        config_schema={
            "title": "NomeDaPlataforma Configuration",
            "type": "object",
            "required": ["campo_obrigatorio1", "campo_obrigatorio2"],
            "properties": {
                "campo_obrigatorio1": {
                    "type": "string",
                    "title": "Campo Obrigatório 1",
                    "description": "Descrição do campo"
                },
                "campo_opcional": {
                    "type": "string",
                    "title": "Campo Opcional",
                    "description": "Descrição do campo opcional"
                }
            }
        },
        auth_config={
            # Configurações específicas para autenticação
            # Exemplo para OAuth2:
            "oauth_authorization_url": "URL_para_autorização",
            "oauth_token_url": "URL_para_obter_token",
            "scopes": ["escopos_necessários"]
        },
        data_mapping_spec={
            # Especificações para mapeamento de dados
            "order_fields": {
                "order_id": "campo_para_id_do_pedido",
                "customer_name": "campo_para_nome_do_cliente",
                # outros campos...
            },
            "product_fields": {
                "sku": "campo_para_sku",
                "name": "campo_para_nome",
                # outros campos...
            }
        }
    )
```

### 2. Registrar o Módulo

Adicione a chamada para sua função no método `get_all_platform_modules()`:

```python
def get_all_platform_modules():
    """Get all platform module definitions"""
    return [
        get_shopee_module_definition(),
        get_amazon_module_definition(),
        get_mercado_livre_module_definition(),
        get_shein_module_definition(),
        get_nome_da_plataforma_module_definition()  # Adicione esta linha
    ]
```

### 3. Implementar Lógica de Autenticação

Dependendo do tipo de autenticação, você pode precisar implementar lógica específica:

#### Para OAuth2:
- Implemente o fluxo de autorização
- Lide com a troca de código por token
- Implemente a renovação de token

#### Para API Key:
- Valide a chave fornecida
- Teste a conexão com a API

#### Para Autenticação Básica:
- Armazene credenciais com segurança
- Implemente a codificação apropriada

### 4. Implementar Serviços de Integração

Crie serviços específicos para sua plataforma que herdem ou utilizem os serviços existentes:

```python
# Exemplo de serviço específico para NomeDaPlataforma
class NomeDaPlataformaService:
    def __init__(self, credentials):
        self.credentials = credentials
        # Inicialize o cliente da API conforme necessário
    
    def get_orders(self, params=None):
        """Obter pedidos da plataforma"""
        # Implemente a lógica para obter pedidos
        pass
    
    def get_products(self, params=None):
        """Obter produtos da plataforma"""
        # Implemente a lógica para obter produtos
        pass
    
    def sync_data(self):
        """Sincronizar dados com a plataforma"""
        # Implemente a lógica de sincronização
        pass
```

### 5. Atualizar o Script de Registro

Certifique-se de que o script `modules/register_modules.py` inclui seu novo módulo:

```python
def register_platform_modules():
    """Register all platform modules in the marketplace"""
    print("Registering platform modules in the integration marketplace...")
    
    modules = get_all_platform_modules()  # Isso agora inclui seu módulo
    
    for module in modules:
        # ... lógica de registro ...
```

### 6. Testar o Módulo

Após implementar seu módulo:

1. Execute o script de registro para adicionar o módulo ao marketplace:
   ```bash
   python -m modules.register_modules
   ```

2. Acesse o marketplace no frontend e verifique se seu módulo aparece

3. Tente instalar uma instância do módulo

4. Teste a funcionalidade completa (autenticação, sincronização, etc.)

## Considerações Importantes

### Segurança
- Armazene credenciais com segurança
- Utilize criptografia onde apropriado
- Siga as melhores práticas de segurança da plataforma

### Escalabilidade
- Projete seu módulo para suportar múltiplas instâncias
- Considere limites de taxa (rate limiting) da API
- Implemente tratamento adequado de erros

### Manutenção
- Documente bem seu código
- Forneça logs adequados para depuração
- Considere a evolução da API da plataforma ao longo do tempo

### UX/UI
- Forneça instruções claras para configuração
- Use validação adequada nos campos de configuração
- Forneça feedback claro sobre o status da integração

## Exemplo Completo

Veja os módulos existentes (Shopee, Amazon, Mercado Livre, Shein) no arquivo `modules/platform_modules.py` para exemplos completos de implementação.

## Deploy

Após desenvolver e testar seu módulo:

1. Certifique-se de que ele está registrado no sistema
2. Atualize a documentação conforme necessário
3. Faça deploy das alterações para o ambiente de produção
4. Execute o script de registro para adicionar o módulo ao marketplace em produção

Com esses passos, seu novo módulo de integração estará disponível para os usuários instalarem e utilizarem no marketplace da aplicação.