#!/bin/bash
# ===========================================
# NISTIPRINT - LOG MANAGEMENT SCRIPT
# ===========================================
# Utilitários para visualizar e gerenciar logs
# Retenção automática: 7 dias
# ===========================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Diretório de logs do Docker
LOG_DIR="/var/lib/docker/containers"

# ===========================================
# FUNÇÕES
# ===========================================

show_help() {
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   NISTIPRINT - LOG MANAGEMENT TOOL      ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Uso: $0 <comando> [opções]"
    echo ""
    echo -e "Comandos disponíveis:"
    echo -e "  ${GREEN}status${NC}          - Mostra status dos logs de todos os containers"
    echo -e "  ${GREEN}size${NC}            - Mostra tamanho dos logs de cada container"
    echo -e "  ${GREEN}clean${NC}           - Limpa logs com mais de 7 dias"
    echo -e "  ${GREEN}follow <svc>${NC}    - Logs em tempo real de um serviço"
    echo -e "  ${GREEN}tail <svc> [n]${NC}  - Últimas n linhas (padrão: 100)"
    echo -e "  ${GREEN}search <svc> <term> - Busca termo nos logs"
    echo -e "  ${GREEN}export <svc>${NC}    - Exporta logs para arquivo"
    echo -e "  ${GREEN}help${NC}            - Mostra esta ajuda"
    echo ""
    echo -e "Serviços disponíveis:"
    echo -e "  ${YELLOW}produção:${NC} frontend, api"
    echo -e "  ${YELLOW}local:${NC}    frontend, api, worker, celery-beat, redis"
    echo ""
}

show_status() {
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   STATUS DOS CONTAINERS E LOGS          ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null || {
        echo -e "${RED}Erro: Não foi possível acessar o Docker${NC}"
        exit 1
    }
    echo ""
    echo -e "${YELLOW}Logs estão configurados com retenção automática:${NC}"
    echo -e "  - Driver: local"
    echo -e "  - Max size por arquivo: 10MB"
    echo -e "  - Max arquivos: 10 (100MB por container)"
    echo -e "  - Compressão: ativada"
    echo ""
}

show_log_size() {
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   TAMANHO DOS LOGS POR CONTAINER        ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    
    for container in $(docker ps -q); do
        name=$(docker inspect --format='{{.Name}}' "$container" | sed 's/^\///')
        log_path=$(docker inspect --format='{{.LogPath}}' "$container")
        
        if [ -f "$log_path" ]; then
            size=$(du -sh "$log_path" 2>/dev/null | cut -f1)
            echo -e "  ${GREEN}$name${NC}: $size"
        fi
    done
    echo ""
}

clean_old_logs() {
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   LIMPEZA DE LOGS ANTIGOS (>7 dias)     ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Nota: O Docker gerencia automaticamente a rotação de logs.${NC}"
    echo -e "${YELLOW}Esta ação irá truncar logs atuais para liberar espaço.${NC}"
    echo ""
    read -p "Deseja continuar? (s/N): " confirm
    
    if [ "$confirm" = "s" ] || [ "$confirm" = "S" ]; then
        for container in $(docker ps -q); do
            name=$(docker inspect --format='{{.Name}}' "$container" | sed 's/^\///')
            echo -e "  Limpando logs de ${GREEN}$name${NC}..."
            docker logs "$container" > /dev/null 2>&1 || true
        done
        echo -e "${GREEN}✓ Logs limpos com sucesso!${NC}"
    else
        echo "Operação cancelada."
    fi
}

follow_logs() {
    local service=$1
    if [ -z "$service" ]; then
        echo -e "${RED}Erro: Especifique um serviço${NC}"
        echo "Uso: $0 follow <serviço>"
        exit 1
    fi
    
    echo -e "${BLUE}Monitorando logs de '$service' (Ctrl+C para sair)...${NC}"
    echo ""
    
    # Tenta encontrar o container pelo nome
    local container=$(docker ps --filter "name=$service" --format "{{.ID}}")
    
    if [ -z "$container" ]; then
        echo -e "${RED}Erro: Container '$service' não encontrado${NC}"
        exit 1
    fi
    
    docker logs -f "$container" --tail 50
}

tail_logs() {
    local service=$1
    local lines=${2:-100}
    
    if [ -z "$service" ]; then
        echo -e "${RED}Erro: Especifique um serviço${NC}"
        echo "Uso: $0 tail <serviço> [n_linhas]"
        exit 1
    fi
    
    local container=$(docker ps --filter "name=$service" --format "{{.ID}}")
    
    if [ -z "$container" ]; then
        echo -e "${RED}Erro: Container '$service' não encontrado${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}Últimas $lines linhas de '$service':${NC}"
    echo ""
    docker logs "$container" --tail "$lines"
}

search_logs() {
    local service=$1
    local term=$2
    
    if [ -z "$service" ] || [ -z "$term" ]; then
        echo -e "${RED}Erro: Especifique serviço e termo de busca${NC}"
        echo "Uso: $0 search <serviço> <termo>"
        exit 1
    fi
    
    local container=$(docker ps --filter "name=$service" --format "{{.ID}}")
    
    if [ -z "$container" ]; then
        echo -e "${RED}Erro: Container '$service' não encontrado${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}Buscando '$term' nos logs de '$service':${NC}"
    echo ""
    docker logs "$container" 2>&1 | grep -i --color=auto "$term" | tail -50
}

export_logs() {
    local service=$1
    
    if [ -z "$service" ]; then
        echo -e "${RED}Erro: Especifique um serviço${NC}"
        echo "Uso: $0 export <serviço>"
        exit 1
    fi
    
    local container=$(docker ps --filter "name=$service" --format "{{.ID}}")
    
    if [ -z "$container" ]; then
        echo -e "${RED}Erro: Container '$service' não encontrado${NC}"
        exit 1
    fi
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local filename="logs_${service}_${timestamp}.txt"
    
    echo -e "${BLUE}Exportando logs de '$service' para $filename...${NC}"
    docker logs "$container" > "$filename" 2>&1
    echo -e "${GREEN}✓ Logs exportados: $filename${NC}"
}

# ===========================================
# MAIN
# ===========================================

case "${1:-help}" in
    status)
        show_status
        ;;
    size)
        show_log_size
        ;;
    clean)
        clean_old_logs
        ;;
    follow)
        follow_logs "$2"
        ;;
    tail)
        tail_logs "$2" "$3"
        ;;
    search)
        search_logs "$2" "$3"
        ;;
    export)
        export_logs "$2"
        ;;
    help|*)
        show_help
        ;;
esac
