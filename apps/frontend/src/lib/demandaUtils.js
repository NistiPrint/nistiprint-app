export const formatDate = dateString => {
  if (!dateString) return '-'
  try {
    // Assuming dateString is YYYY-MM-DD or ISO
    const date = new Date(dateString)
    return date.toLocaleDateString('pt-BR')
  } catch (e) {
    return dateString
  }
}

export const formatDateTime = dateString => {
  if (!dateString) return '-'
  try {
    const date = new Date(dateString)
    return date.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch (e) {
    return dateString
  }
}

export const calculateTimeRemaining = (horarioColeta, dataEntrega) => {
  if (!horarioColeta || !dataEntrega) return { text: null, color: 'text-gray-400' }

  // Create a timezone-aware date combining the delivery date and collection time
  const [hours, minutes] = horarioColeta.split(':')

  // Create the collection time in the user's local timezone
  const coletaTime = new Date(`${dataEntrega}T${hours}:${minutes}:00`)

  // Get current time in the user's timezone
  const now = new Date()

  // If coleta time is already passed
  if (coletaTime <= now) {
    return { text: 'Expirado', color: 'text-red-700' }
  }

  const diffMs = coletaTime - now
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffHours / 24)
  const remainingHours = diffHours % 24
  const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

  let text = ''
  if (diffDays > 0) {
    if (remainingHours > 0) {
      text = `${diffDays}d ${remainingHours}h`
    } else {
      text = `${diffDays}d`
    }
  } else if (diffHours > 0) {
    text = `${diffHours}h ${diffMinutes}min`
  } else if (diffMinutes > 0) {
    text = `${diffMinutes}min`
  } else {
    text = 'Agora'
  }

  // Semantic colors
  let color = 'text-green-600'
  if (diffHours < 1) {
    color = 'text-red-600 font-bold'
  } else if (diffHours < 4) {
    color = 'text-amber-600 font-bold'
  }

  return { text, color }
}

export const getStatusIcon = status => {
  switch (status) {
    case 'Finalizado':
    case 'Concluída':
    case 'Concluído':
    case 'CONCLUIDO':
      return 'CheckCircle'
    case 'Coletado':
    case 'Coletada':
      return 'Truck'
    case 'Em Produção':
    case 'EM_PRODUCAO':
      return 'Factory'
    default:
      return 'Clock'
  }
}

export const getStatusColor = status => {
  const colors = {
    Finalizado: 'text-green-600 bg-green-50 border-green-200',
    'Concluída': 'text-green-600 bg-green-50 border-green-200',
    'Concluído': 'text-green-600 bg-green-50 border-green-200',
    CONCLUIDO: 'text-green-600 bg-green-50 border-green-200',
    'Em Produção': 'text-blue-600 bg-blue-50 border-blue-200',
    EM_PRODUCAO: 'text-blue-600 bg-blue-50 border-blue-200',
    Pendente: 'text-amber-600 bg-amber-50 border-amber-200',
    AGUARDANDO: 'text-amber-600 bg-amber-50 border-amber-200',
    Atrasado: 'text-red-600 bg-red-50 border-red-200',
    'Coletado': 'text-purple-600 bg-purple-50 border-purple-200',
    'Coletada': 'text-purple-600 bg-purple-50 border-purple-200',
    COLETA_PARCIAL: 'text-orange-600 bg-orange-50 border-orange-200',
  }
  return colors[status] || 'text-gray-600 bg-gray-50 border-gray-200'
}

// Calcular dias restantes considerando o fuso horário
export const diasRestantes = dataEntrega => {
  // Criar datas com horário 00:00:00 no fuso horário local
  const hoje = new Date()
  hoje.setHours(0, 0, 0, 0)

  const entrega = new Date(dataEntrega)
  entrega.setHours(0, 0, 0, 0)

  const diffTime = entrega - hoje
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

  return diffDays
}

export const isUrgente = (dataEntrega, horarioColeta) => {
  if (!horarioColeta || !dataEntrega) return false

  const [hours, minutes] = horarioColeta.split(':')
  const coletaTime = new Date(`${dataEntrega}T${hours}:${minutes}:00`)
  const now = new Date()

  // If coleta time has already passed, not urgent
  if (coletaTime <= now) return false

  const diffMs = coletaTime - now
  const diffHours = diffMs / (1000 * 60 * 60)

  return diffHours < 2
}
