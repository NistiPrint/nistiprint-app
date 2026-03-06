
/**
 * Verifica se uma demanda requer ação do setor atual do usuário.
 * 
 * Setores conhecidos: 'CPD', 'miolos', 'capas', 'expedição'
 */
export const checkActionRequired = (demanda, setorNome) => {
    if (!demanda || !setorNome) return false;
    
    const setor = setorNome.toLowerCase();
    
    // Regras para Expedição
    if (setor === 'expedição' || setor === 'expedicao') {
        // Se houver itens prontos para retirada (Capas ou Miolos)
        // E ainda não foram totalmente coletados/expedidos
        const temCapasProntas = (demanda.capas_prontas_retirada_qtd || 0) > 0;
        const temMiolosProntos = (demanda.miolos_prontos_retirada_qtd || 0) > 0;
        
        // Se status já é Finalizado ou Coletado, não requer ação imediata de produção/retirada (apenas arquivamento talvez)
        if (demanda.status === 'Finalizado' || demanda.status === 'Coletado') return false;

        return temCapasProntas || temMiolosProntos;
    }

    // Regras para Capas
    if (setor === 'capas') {
        // Se a demanda está em produção e ainda falta produzir capas
        // Ou se há capas impressas esperando montagem
        if (demanda.status === 'Em Produção' || demanda.status === 'Pendente') {
            const total = demanda.total_itens || demanda.total_quantidade || 0;
            const produzidas = demanda.capas_produzidas_qtd || 0;
            const prontas = demanda.capas_prontas_retirada_qtd || 0;
            
            // Se ainda não produziu tudo
            if (produzidas + prontas < total) return true;
        }
        return false;
    }

    // Regras para Miolos
    if (setor === 'miolos') {
        if (demanda.status === 'Em Produção' || demanda.status === 'Pendente') {
            const total = demanda.total_itens || demanda.total_quantidade || 0;
            const produzidos = demanda.miolos_produzidos_qtd || 0;
            const prontos = demanda.miolos_prontos_retirada_qtd || 0;
            
            if (produzidos + prontos < total) return true;
        }
        return false;
    }

    // Regras para CPD
    if (setor === 'cpd') {
        // CPD geralmente cuida do início do processo ou problemas
        if (demanda.status === 'Pendente' || demanda.status === 'Aguardando arte') return true;
        if (demanda.status === 'Atrasado') return true;
    }

    return false;
};

/**
 * Retorna uma mensagem de notificação apropriada
 */
export const getNotificationMessage = (demanda, setorNome) => {
    const setor = setorNome.toLowerCase();
    
    if (setor === 'expedição' || setor === 'expedicao') {
        return `Itens prontos para retirada na demanda: ${demanda.nome}`;
    }
    
    if (setor === 'capas' || setor === 'miolos') {
        return `Nova produção pendente: ${demanda.nome}`;
    }
    
    if (setor === 'cpd') {
        if (demanda.status === 'Atrasado') return `Demanda ATRASADA: ${demanda.nome}`;
        return `Nova demanda pendente: ${demanda.nome}`;
    }
    
    return `Ação necessária na demanda: ${demanda.nome}`;
};
