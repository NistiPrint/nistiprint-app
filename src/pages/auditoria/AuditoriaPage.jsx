import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { Calendar, Eye, Filter, RefreshCw, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

const AuditoriaPage = () => {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    event_type: 'all',
    user_id: '',
    start_date: '',
    end_date: '',
    limit: 100
  });
  const [entitySearch, setEntitySearch] = useState({
    entity_type: '',
    entity_id: ''
  });

  // Carregar eventos iniciais
  useEffect(() => {
    loadAuditEvents();
  }, []);

  const loadAuditEvents = async () => {
    setLoading(true);
    try {
      const queryParams = new URLSearchParams();

      Object.entries(filters).forEach(([key, value]) => {
        // Não incluir filtros vazios ou "all"
        if (value && value !== 'all') {
          queryParams.append(key, value);
        }
      });

      const response = await fetch(`/producao/api/auditoria?${queryParams}`);
      const data = await response.json();

      if (data.success) {
        setEvents(data.events);
      } else {
        toast.error('Erro ao carregar eventos de auditoria');
      }
    } catch (error) {
      console.error('Erro ao carregar auditoria:', error);
      toast.error('Erro ao carregar eventos de auditoria');
    } finally {
      setLoading(false);
    }
  };

  const loadEventsByEntity = async () => {
    if (!entitySearch.entity_type || !entitySearch.entity_id) {
      toast.warning('Selecione o tipo e ID da entidade');
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(
        `/producao/api/auditoria/entidade/${entitySearch.entity_type}/${entitySearch.entity_id}`
      );
      const data = await response.json();

      if (data.success) {
        setEvents(data.events);
        toast.success(`Encontrados ${data.total} eventos para ${entitySearch.entity_type} ${entitySearch.entity_id}`);
      } else {
        toast.error('Erro ao buscar eventos da entidade');
      }
    } catch (error) {
      console.error('Erro ao buscar eventos por entidade:', error);
      toast.error('Erro ao buscar eventos da entidade');
    } finally {
      setLoading(false);
    }
  };

  const handleFilterChange = (field, value) => {
    setFilters(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleEntitySearchChange = (field, value) => {
    setEntitySearch(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const clearFilters = () => {
    setFilters({
      event_type: 'all',
      user_id: '',
      start_date: '',
      end_date: '',
      limit: 100
    });
  };

  const getEventTypeColor = (eventType) => {
    const colors = {
      'ENTRADA_ESTOQUE': 'bg-green-100 text-green-800',
      'SAIDA_ESTOQUE': 'bg-red-100 text-red-800',
      'SAIDA_DISTRIBUIDA_DEMANDA': 'bg-blue-100 text-blue-800',
      'REVERSAO_LANCAMENTO': 'bg-orange-100 text-orange-800',
      'PRODUCAO_REGISTRADA': 'bg-purple-100 text-purple-800'
    };
    return colors[eventType] || 'bg-gray-100 text-gray-800';
  };

  const formatPayload = (payload) => {
    if (!payload) return 'N/A';

    // Formatar diferentes tipos de payload
    const formatted = Object.entries(payload).map(([key, value]) => {
      if (typeof value === 'object') {
        return `${key}: ${JSON.stringify(value)}`;
      }
      return `${key}: ${value}`;
    });

    return formatted.join(', ');
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'N/A';
    try {
      return format(new Date(timestamp.seconds * 1000), 'dd/MM/yyyy HH:mm:ss', { locale: ptBR });
    } catch {
      return timestamp.toString();
    }
  };

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Auditoria do Sistema</h1>
          <p className="text-gray-600 mt-1">
            Rastreamento completo de todas as operações críticas do sistema
          </p>
        </div>
        <Button onClick={loadAuditEvents} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </div>

      {/* Filtros Gerais */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="h-5 w-5" />
            Filtros Gerais
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <div>
              <Label htmlFor="event_type">Tipo de Evento</Label>
              <Select
                value={filters.event_type}
                onValueChange={(value) => handleFilterChange('event_type', value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Todos os tipos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os tipos</SelectItem>
                  <SelectItem value="ENTRADA_ESTOQUE">Entrada de Estoque</SelectItem>
                  <SelectItem value="SAIDA_ESTOQUE">Saída de Estoque</SelectItem>
                  <SelectItem value="SAIDA_DISTRIBUIDA_DEMANDA">Saída Distribuída</SelectItem>
                  <SelectItem value="REVERSAO_LANCAMENTO">Reversão de Lançamento</SelectItem>
                  <SelectItem value="PRODUCAO_REGISTRADA">Produção Registrada</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="user_id">Usuário</Label>
              <Input
                id="user_id"
                placeholder="ID do usuário"
                value={filters.user_id}
                onChange={(e) => handleFilterChange('user_id', e.target.value)}
              />
            </div>

            <div>
              <Label htmlFor="start_date">Data Inicial</Label>
              <Input
                id="start_date"
                type="date"
                value={filters.start_date}
                onChange={(e) => handleFilterChange('start_date', e.target.value)}
              />
            </div>

            <div>
              <Label htmlFor="end_date">Data Final</Label>
              <Input
                id="end_date"
                type="date"
                value={filters.end_date}
                onChange={(e) => handleFilterChange('end_date', e.target.value)}
              />
            </div>

            <div className="flex items-end gap-2">
              <Button onClick={loadAuditEvents} className="flex-1">
                <Search className="h-4 w-4 mr-2" />
                Buscar
              </Button>
              <Button variant="outline" onClick={clearFilters}>
                Limpar
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Busca por Entidade */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Eye className="h-5 w-5" />
            Buscar por Entidade Específica
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <Label htmlFor="entity_type">Tipo de Entidade</Label>
              <Select
                value={entitySearch.entity_type}
                onValueChange={(value) => handleEntitySearchChange('entity_type', value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Selecione o tipo" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="produto">Produto</SelectItem>
                  <SelectItem value="demanda">Demanda</SelectItem>
                  <SelectItem value="lancamento">Lançamento</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="entity_id">ID da Entidade</Label>
              <Input
                id="entity_id"
                placeholder="Digite o ID"
                value={entitySearch.entity_id}
                onChange={(e) => handleEntitySearchChange('entity_id', e.target.value)}
              />
            </div>

            <div className="col-span-2 flex items-end">
              <Button onClick={loadEventsByEntity} disabled={loading}>
                <Search className="h-4 w-4 mr-2" />
                Buscar Eventos da Entidade
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabela de Eventos */}
      <Card>
        <CardHeader>
          <CardTitle>
            Eventos de Auditoria ({events.length} encontrados)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center items-center py-8">
              <RefreshCw className="h-8 w-8 animate-spin text-gray-400" />
              <span className="ml-2 text-gray-600">Carregando eventos...</span>
            </div>
          ) : events.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <Calendar className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>Nenhum evento encontrado com os filtros aplicados.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Data/Hora</TableHead>
                    <TableHead>Tipo de Evento</TableHead>
                    <TableHead>Usuário</TableHead>
                    <TableHead>Detalhes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((event) => (
                    <TableRow key={event.id}>
                      <TableCell className="font-mono text-sm">
                        {formatTimestamp(event.timestamp)}
                      </TableCell>
                      <TableCell>
                        <Badge className={getEventTypeColor(event.event_type)}>
                          {event.event_type.replace(/_/g, ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {event.user_id || 'Sistema'}
                      </TableCell>
                      <TableCell className="max-w-md">
                        <div className="text-sm text-gray-600 truncate" title={formatPayload(event.payload)}>
                          {formatPayload(event.payload)}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default AuditoriaPage;
