import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useRealtimeDemandas } from '@/lib/hooks/useRealtimeDemandas';
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, Clock } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

function DemandaCalendarPage() {
  const [viewMode, setViewMode] = useState('week'); // 'week' or 'day'
  const [currentDate, setCurrentDate] = useState(new Date());
  const { demandas, loading, error } = useRealtimeDemandas(5000); // Use the realtime hook

  // No need for separate fetchDemandas and useEffect for demands here, hook handles it.

  const getDaysInWeek = (date) => {
    const days = [];
    const start = new Date(date);
    start.setDate(start.getDate() - start.getDay()); // Sunday
    for (let i = 0; i < 7; i++) {
      const day = new Date(start);
      day.setDate(start.getDate() + i);
      days.push(day);
    }
    return days;
  };

  const navigate = (direction) => {
    const newDate = new Date(currentDate);
    if (viewMode === 'week') {
      newDate.setDate(newDate.getDate() + (direction * 7));
    } else {
      newDate.setDate(newDate.getDate() + direction);
    }
    setCurrentDate(newDate);
  };

  const getDemandasForDate = (date) => {
    const dateStr = date.toISOString().split('T')[0];
    return demandas.filter(d => d.data_entrega === dateStr || (d.data_finalizacao_prevista && d.data_finalizacao_prevista.startsWith(dateStr)));
  };

  const getDemandasForTime = (date, hour) => {
    const dateStr = date.toISOString().split('T')[0];
    return demandas.filter(d => {
        if (d.data_entrega !== dateStr) return false;
        if (!d.horario_coleta) return false;
        const dHour = parseInt(d.horario_coleta.split(':')[0]);
        return dHour === hour;
    });
  };

  const weekDays = getDaysInWeek(currentDate);
  const hours = Array.from({ length: 14 }, (_, i) => i + 6); // 06:00 to 19:00

  const renderEventCard = (demanda, compact = false) => (
    <Link to={`/producao/demanda/${demanda.id}/dashboard`} key={demanda.id} className="block mb-2">
      <div 
        className={`p-2 rounded border text-xs ${['Finalizado', 'CONCLUIDO'].includes(demanda.status) ? 'bg-green-50 border-green-200' : 'bg-white border-gray-200 shadow-sm'} hover:shadow-md transition-shadow`}
      >
        <div className="font-bold truncate">{demanda.nome}</div>
        {!compact && (
          <>
            {demanda.canal_venda_plataforma && (
              <Badge 
                variant="outline" 
                style={{ backgroundColor: demanda.canal_venda_color, color: 'white' }} 
                className="text-[10px] h-4 px-1 py-0 mt-1"
              >
                {demanda.canal_venda_plataforma}
              </Badge>
            )}
            <div className="flex items-center gap-1 text-gray-500 mt-1">
              <Clock className="w-3 h-3" />
              <span>{demanda.horario_coleta || 'S/H'}</span>
              {demanda.flex && <Badge variant="outline" className="text-[10px] h-4 px-1 py-0">Flex</Badge>}
            </div>
            <div className="mt-1 text-gray-400">{demanda.canal_venda_nome}</div>
            {demanda.tipo_demanda === 'Empresas' && (
                <div className="text-[10px] text-gray-600 mt-1">
                    <p className="font-medium truncate">Empresa: {demanda.empresa_cliente_nome}</p>
                    <p className="truncate">Status: {demanda.empresa_interacao_status}</p>
                </div>
            )}
          </>
        )}
      </div>
    </Link>
  );

  return (
    <div className="container mx-auto py-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <CalendarIcon className="w-8 h-8" /> Calendário de Produção
        </h1>
        <div className="flex items-center gap-4">
           <Select value={viewMode} onValueChange={setViewMode}>
            <SelectTrigger className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="week">Semana</SelectItem>
              <SelectItem value="day">Dia</SelectItem>
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2 border rounded-md p-1">
            <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="font-medium min-w-[150px] text-center">
              {viewMode === 'week' 
                ? `${weekDays[0].toLocaleDateString()} - ${weekDays[6].toLocaleDateString()}`
                : currentDate.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
              }
            </span>
            <Button variant="ghost" size="icon" onClick={() => navigate(1)}>
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>

      {loading ? (
        <div>Carregando...</div>
      ) : (
        <Card>
          <CardContent className="p-0">
            {viewMode === 'week' ? (
              <div className="grid grid-cols-7 divide-x divide-gray-200">
                {weekDays.map((day, i) => {
                  const dayEvents = getDemandasForDate(day);
                  const isToday = day.toDateString() === new Date().toDateString();
                  return (
                    <div key={i} className={`min-h-[600px] ${isToday ? 'bg-blue-50/30' : ''}`}>
                      <div className={`p-3 border-b text-center ${isToday ? 'bg-blue-100 font-bold' : 'bg-gray-50'}`}>
                        <div className="text-sm text-gray-500 uppercase">{day.toLocaleDateString(undefined, { weekday: 'short' })}</div>
                        <div className="text-lg">{day.getDate()}</div>
                      </div>
                      <div className="p-2">
                        {dayEvents.map(d => renderEventCard(d))}
                        {dayEvents.length === 0 && <div className="text-center text-gray-300 text-xs py-4">Sem entregas</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="divide-y divide-gray-200">
                 {/* Header for Day View */}
                 <div className="grid grid-cols-[100px_1fr] bg-gray-50 font-medium">
                    <div className="p-4 border-r">Horário</div>
                    <div className="p-4">Demandas / Coletas</div>
                 </div>
                 {hours.map(hour => {
                    const timeEvents = getDemandasForTime(currentDate, hour);
                    return (
                        <div key={hour} className="grid grid-cols-[100px_1fr] min-h-[80px]">
                            <div className="p-4 border-r text-gray-500 text-sm font-medium flex items-center justify-center bg-gray-50/50">
                                {hour}:00
                            </div>
                            <div className="p-2 relative">
                                {timeEvents.length > 0 ? (
                                    <div className="flex gap-2 flex-wrap">
                                        {timeEvents.map(d => (
                                            <div key={d.id} className="w-[200px]">
                                                {renderEventCard(d)}
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="absolute inset-0 border-b border-dashed border-gray-100 pointer-events-none" />
                                )}
                            </div>
                        </div>
                    );
                 })}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default DemandaCalendarPage;
