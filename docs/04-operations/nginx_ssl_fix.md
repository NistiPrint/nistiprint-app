## Correção do Erro `ERR_SSL_UNRECOGNIZED_NAME_ALERT` no Nginx Proxy Manager

Este erro indica que o certificado SSL que o seu servidor está apresentando para `app.nistiprint.neolabs.com.br` não é reconhecido ou não cobre este nome de domínio específico. Isso geralmente significa um problema na configuração do SSL no Nginx Proxy Manager (NPM).

Siga estes passos para verificar e corrigir a configuração:

1.  **Acesse o Nginx Proxy Manager (NPM):**
    *   Abra seu navegador e navegue até a interface web do NPM (geralmente `http://seu-servidor-ip:81` ou `https://seu-servidor-ip:4443` se você estiver usando HTTPS para o NPM).
    *   Faça login com suas credenciais.

2.  **Verifique o Host Proxy para `app.nistiprint.neolabs.com.br`:**
    *   No painel do NPM, vá para **"Hosts" > "Proxy Hosts"**.
    *   Localize o registro correspondente ao domínio `app.nistiprint.neolabs.com.br`.

3.  **Edite o Host Proxy (se necessário):**
    *   Clique no ícone de edição (lápis) ao lado do host.

4.  **Aba "Details":**
    *   Certifique-se de que o campo **"Domain Names"** contém exatamente `app.nistiprint.neolabs.com.br`. Se houver qualquer erro de digitação ou nome diferente, corrija-o.
    *   Verifique se o **"Forward Hostname / IP"** está configurado para o nome do seu container frontend (ex: `nistiprint-frontend-prod`) e **"Forward Port"** para `80`.

5.  **Aba "SSL":**
    *   Certifique-se de que **"SSL Certificate"** está definido para um certificado válido. Idealmente, você deve estar usando um certificado Let's Encrypt gerado pelo próprio NPM.
    *   Se o certificado estiver expirado ou não foi gerado/renovado corretamente:
        *   Selecione **"Request a new SSL Certificate"**.
        *   Ative a opção **"Force SSL"** (altamente recomendado).
        *   Ative a opção **"I Agree to the Let's Encrypt Terms of Service"**.
        *   Clique em **"Save"**. O NPM tentará emitir um novo certificado.

6.  **Verifique os Logs do NPM:**
    *   Se a emissão do certificado falhar, verifique os logs do container do Nginx Proxy Manager para obter mais detalhes sobre o motivo da falha. Você pode fazer isso via Portainer (vá para **"Containers"**, localize o container do NPM, e clique em **"Logs"**) ou via SSH no seu servidor (`docker logs <nome_do_container_npm>`). Erros comuns incluem problemas de DNS (seu domínio não apontando para o IP correto do servidor) ou firewall bloqueando o tráfego HTTP/HTTPS para os desafios do Let's Encrypt.

7.  **Limpe o Cache do Navegador:**
    *   Após qualquer alteração no NPM, é uma boa prática limpar o cache do seu navegador ou tentar acessar o site em uma janela anônima para garantir que você está vendo a versão mais recente e não uma versão em cache.

**Considerações Finais:**

*   **Verifique o DNS:** Certifique-se de que o registro DNS `app.nistiprint.neolabs.com.br` (tipo A) está apontando para o endereço IP público do seu servidor onde o Nginx Proxy Manager está rodando. Sem isso, o Let's Encrypt não conseguirá verificar a posse do domínio.
*   **Firewall:** Verifique se as portas `80` (HTTP) e `443` (HTTPS) estão abertas no firewall do seu servidor para que o NPM possa receber as requisições e o Let's Encrypt possa realizar a validação.

Após seguir estes passos, a sua aplicação frontend deve estar acessível via HTTPS sem o erro `ERR_SSL_UNRECOGNIZED_NAME_ALERT`.