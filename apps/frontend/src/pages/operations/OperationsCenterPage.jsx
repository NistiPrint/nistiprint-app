import { Navigate, useParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import TaskControlCenter from '@/pages/admin/TaskControlCenter';
import AuditoriaPage from '@/pages/auditoria/AuditoriaPage';
import MyActivityPage from './MyActivityPage';
import GlobalOperationsHistory from './GlobalOperationsHistory';

const GLOBAL_AREAS = new Set(['visao-geral', 'execucoes', 'filas']);
const ADMIN_AREAS = new Set(['agendamentos', 'manutencao']);

export default function OperationsCenterPage() {
  const { area = 'minha-atividade' } = useParams();
  const { user, isAdmin, hasPermission } = useAuth();

  if (area === 'minha-atividade' || area === 'minha-atividade/') return <MyActivityPage />;
  if (area === 'auditoria') {
    if (isAdmin() || hasPermission('auditoria', 'ler')) return <AuditoriaPage />;
    return <Navigate to="/monitoramento/operacoes/minha-atividade" replace />;
  }
  if (GLOBAL_AREAS.has(area)) {
    if (isAdmin() || user?.can_view_operations || hasPermission('central_operacoes', 'ler')) {
      return <><TaskControlCenter basePath="/monitoramento/operacoes" />{area === 'execucoes' && <GlobalOperationsHistory />}</>;
    }
    return <Navigate to="/monitoramento/operacoes/minha-atividade" replace />;
  }
  if (ADMIN_AREAS.has(area)) {
    if (isAdmin()) return <TaskControlCenter basePath="/monitoramento/operacoes" />;
    return <Navigate to="/monitoramento/operacoes/minha-atividade" replace />;
  }
  return <Navigate to="/monitoramento/operacoes/minha-atividade" replace />;
}
