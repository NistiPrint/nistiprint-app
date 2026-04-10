import { Navigate, Route, Routes } from 'react-router-dom'
import GerencialHistorico from './components/GerencialHistorico'
import ProtectedRoute from './components/ProtectedRoute'
import MainLayout from './components/layout/MainLayout'
import InstallWizard from './components/marketplace/InstallWizard'
import { Toaster } from './components/ui/sonner'
import { LayoutProvider } from './contexts/LayoutContext'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import CadastrosPage from './pages/admin/CadastrosPage'
import ConfiguracoesPage from './pages/admin/ConfiguracoesPage'
import FerramentasPage from './pages/admin/FerramentasPage'
import IntegracoesPage from './pages/admin/IntegracoesPage'
import RelatoriosPage from './pages/admin/RelatoriosPage'
import SetorPermissoesPage from './pages/admin/SetorPermissoesPage'; // Import SetorPermissoesPage
import SistemaPage from './pages/admin/SistemaPage'
import CanalVendaFormPage from './pages/admin/cadastros/CanalVendaFormPage'; // Import CanalVendaFormPage
import CanalVendaListPage from './pages/admin/cadastros/CanalVendaListPage'; // Import CanalVendaListPage
import CategoriaFormPage from './pages/admin/cadastros/CategoriaFormPage'
import CategoriaListPage from './pages/admin/cadastros/CategoriaListPage'
import DepositoFormPage from './pages/admin/cadastros/DepositoFormPage'
import DepositoListPage from './pages/admin/cadastros/DepositoListPage'
import FornecedorFormPage from './pages/admin/cadastros/FornecedorFormPage'
import FornecedorListPage from './pages/admin/cadastros/FornecedorListPage'
import PlataformaFormPage from './pages/admin/cadastros/PlataformaFormPage'; // Import PlataformaFormPage
import PlataformaListPage from './pages/admin/cadastros/PlataformaListPage'; // Import PlataformaListPage
import PontoColetaFormPage from './pages/admin/cadastros/PontoColetaFormPage'
import PontoColetaListPage from './pages/admin/cadastros/PontoColetaListPage'
import SetorFormPage from './pages/admin/cadastros/SetorFormPage'
import SetorListPage from './pages/admin/cadastros/SetorListPage'
import TagFormPage from './pages/admin/cadastros/TagFormPage'; // Import TagFormPage
import TagListPage from './pages/admin/cadastros/TagListPage'; // Import TagListPage
import UnidadeMedidaFormPage from './pages/admin/cadastros/UnidadeMedidaFormPage'
import UnidadeMedidaListPage from './pages/admin/cadastros/UnidadeMedidaListPage'
import UomConversionFormPage from './pages/admin/cadastros/UomConversionFormPage'
import UomConversionsListPage from './pages/admin/cadastros/UomConversionsListPage'
import UsuarioFormPage from './pages/admin/cadastros/UsuarioFormPage'
import UsuarioListPage from './pages/admin/cadastros/UsuarioListPage'
import ConfiguracoesBlingPage from './pages/admin/configuracoes/ConfiguracoesBlingPage'
import ConfiguracoesProducaoPage from './pages/admin/configuracoes/ConfiguracoesProducaoPage'
import IntegrationRoutingPage from './pages/admin/configuracoes/IntegrationRoutingPage'
import PermissoesDemandaPage from './pages/admin/configuracoes/PermissoesDemandaPage'
import FilaEstoquePage from './pages/admin/relatorios/FilaEstoquePage'
import MonitoramentoEstoquePage from './pages/admin/relatorios/MonitoramentoEstoquePage'
import MonitoramentoPage from './pages/admin/relatorios/MonitoramentoPage'
import HistoricoColetasPage from './pages/admin/relatorios/HistoricoColetasPage'
import HistoricoProducaoPage from './pages/admin/relatorios/HistoricoProducaoPage'
import RelatoriosIndexPage from './pages/admin/relatorios/RelatoriosIndexPage'
import AIDashboardPage from './pages/ai/AIDashboardPage'
import { AILogsPage } from './pages/ai/AILogsPage'
import AuditoriaPage from './pages/auditoria/AuditoriaPage'
import ConsolidarPage from './pages/consolidar/ConsolidarPage'
import ConsolidarReviewPage from './pages/consolidar/ConsolidarReviewPage'
import RascunhosListPage from './pages/consolidar/RascunhosListPage'
import EstoqueAjustePage from './pages/estoque/EstoqueAjustePage'
import EstoqueDashboardPage from './pages/estoque/EstoqueDashboardPage'
import EstoqueHistoricoPage from './pages/estoque/EstoqueHistoricoPage'
import EstoqueMovimentarPage from './pages/estoque/EstoqueMovimentarPage'
import EstoquePosicaoPage from './pages/estoque/EstoquePosicaoPage'
import EstoqueRelatoriosPage from './pages/estoque/EstoqueRelatoriosPage'
import EstoqueReservasPage from './pages/estoque/EstoqueReservasPage'
import MovimentacaoLotePage from './pages/estoque/MovimentacaoLotePage'
import FilaImpressao from './pages/impressao/FilaImpressao'
import ControleProducaoPage from './pages/producao/ControleProducaoPage'
import DemandaCalendarPage from './pages/producao/DemandaCalendarPage'
import DemandaDashboardPage from './pages/producao/DemandaDashboardPage'
import DemandaListPage from './pages/producao/DemandaListPage'
import DemandaPrioridadePage from './pages/producao/DemandaPrioridadePage'
import DemandaRascunhosPage from './pages/producao/DemandaRascunhosPage'
import ExpedicaoDashboardPage from './pages/producao/ExpedicaoDashboardPage'
import FocoProducaoPage from './pages/producao/FocoProducaoPage'
import NovaDemandaPage from './pages/producao/NovaDemandaPage'
import PainelProducaoPage from './pages/producao/PainelProducaoPage'
import ProducaoPage from './pages/producao/ProducaoPage'
import ResumoProducaoPage from './pages/producao/ResumoProducaoPage'
import ProdutoFormPage from './pages/produtos/ProdutoFormPage'
import ProdutoListPage from './pages/produtos/ProdutoListPage'
import PedidoDetalhePage from './pages/pedidos/PedidoDetalhePage'
import PedidosListPage from './pages/pedidos/PedidosListPage'
import VendasPage from './pages/vendas/VendasPage'
import VendasPersonalizadasPage from './pages/vendas/VendasPersonalizadasPage'
import ConfiguracoesIA from './pages/configuracoes/ConfiguracoesIA'
function App() {
  return (
    <>
      <Routes>
        {/* Login Route - outside of MainLayout */}
        <Route path='/login' element={<LoginPage />} />

        <Route
          path='/'
          element={
            <ProtectedRoute>
              <LayoutProvider>
                <MainLayout />
              </LayoutProvider>
            </ProtectedRoute>
          }>
          {/* Dashboard/Home Route */}
          <Route index element={<HomePage />} />

          {/* Produtos Routes */}
          <Route path='produtos' element={<ProdutoListPage />} />
          <Route path='produtos/novo' element={<ProdutoFormPage />} />
          <Route path='produtos/:id/editar' element={<ProdutoFormPage />} />

          {/* Produção Routes */}
          <Route path='producao' element={<ProducaoPage />}>
            <Route index element={<PainelProducaoPage />} />
            <Route path='foco' element={<FocoProducaoPage />} />
            <Route path='resumo' element={<ResumoProducaoPage />} />
            <Route path='demanda' element={<DemandaListPage />} />
            <Route path='demanda/rascunhos' element={<DemandaRascunhosPage />} />
            <Route path='demanda/nova' element={<NovaDemandaPage />} />
            <Route path='demanda/:id/editar' element={<NovaDemandaPage />} />
            <Route
              path='demanda/prioridade'
              element={<DemandaPrioridadePage />}
            />
            <Route
              path='demanda/calendario'
              element={<DemandaCalendarPage />}
            />
            <Route
              path='demanda/:id/dashboard'
              element={<DemandaDashboardPage />}
            />
            <Route
              path='miolos'
              element={<ControleProducaoPage tipo='miolo' />}
            />
            <Route
              path='capas'
              element={<ControleProducaoPage tipo='capa' />}
            />
            <Route path='expedicao' element={<ExpedicaoDashboardPage />} />
            <Route path='impressao' element={<FilaImpressao />} />
          </Route>

          <Route path='vendas' element={<VendasPage />}>
            <Route index element={<Navigate to='pedidos' replace />} />
            <Route
              path='personalizadas'
              element={<VendasPersonalizadasPage />}
            />
            <Route path='identificacao-ia' element={<AIDashboardPage />} />
            <Route path='pedidos' element={<PedidosListPage />} />
            <Route path='pedidos/:id' element={<PedidoDetalhePage />} />
          </Route>

          <Route path='pedidos' element={<PedidosListPage />} />

          {/* Configurações */}
          <Route path='configuracoes'>
            <Route path='ia' element={<ConfiguracoesIA />} />
          </Route>
          <Route path='pedidos/:id' element={<PedidoDetalhePage />} />
          <Route path='consolidar' element={<ConsolidarPage />} />
          <Route path='consolidar/revisao' element={<ConsolidarReviewPage />} />
          <Route path='consolidar/rascunhos' element={<RascunhosListPage />} />

          {/* Estoque Routes */}
          <Route path='estoque'>
            <Route index element={<EstoqueDashboardPage />} />
            <Route path='dashboard' element={<EstoqueDashboardPage />} />
            <Route path='historico' element={<EstoqueHistoricoPage />} />
            <Route path='movimentar' element={<EstoqueMovimentarPage />} />
            <Route path='posicao' element={<EstoquePosicaoPage />} />
            <Route path='reservas' element={<EstoqueReservasPage />} />
            <Route path='ajuste' element={<EstoqueAjustePage />} />
            <Route path='relatorios' element={<EstoqueRelatoriosPage />} />
            <Route
              path='movimentacao-lote'
              element={<MovimentacaoLotePage />}
            />
          </Route>

          {/* Administração Routes - Protegidas para administradores */}
          <Route
            path='cadastros'
            element={
              <ProtectedRoute requireAdmin={true}>
                <CadastrosPage />
              </ProtectedRoute>
            }>
            <Route
              index
              element={<Navigate to='/cadastros/categoria' replace />}
            />
            <Route path='categoria' element={<CategoriaListPage />} />
            <Route path='categoria/novo' element={<CategoriaFormPage />} />
            <Route path='categoria/:id/editar' element={<CategoriaFormPage />} />
            <Route path='tag' element={<TagListPage />} />
            <Route path='tag/novo' element={<TagFormPage />} />
            <Route path='tag/:id/editar' element={<TagFormPage />} />
            <Route path='unidade-medida' element={<UnidadeMedidaListPage />} />
            <Route
              path='unidade-medida/novo'
              element={<UnidadeMedidaFormPage />}
            />
            <Route
              path='unidade-medida/:id/editar'
              element={<UnidadeMedidaFormPage />}
            />
            <Route path='uom-conversions' element={<UomConversionsListPage />} />
            <Route
              path='uom-conversions/new'
              element={<UomConversionFormPage />}
            />
            <Route
              path='uom-conversions/:id/edit'
              element={<UomConversionFormPage />}
            />
            <Route path='fornecedor' element={<FornecedorListPage />} />
            <Route path='fornecedor/novo' element={<FornecedorFormPage />} />
            <Route
              path='fornecedor/:id/editar'
              element={<FornecedorFormPage />}
            />
            <Route path='deposito' element={<DepositoListPage />} />
            <Route path='deposito/novo' element={<DepositoFormPage />} />
            <Route path='deposito/:id/editar' element={<DepositoFormPage />} />
            <Route path='canal-venda' element={<CanalVendaListPage />} />
            <Route path='canal-venda/novo' element={<CanalVendaFormPage />} />
            <Route
              path='canal-venda/:id/editar'
              element={<CanalVendaFormPage />}
            />
            <Route path='plataforma' element={<PlataformaListPage />} />
            <Route path='plataforma/novo' element={<PlataformaFormPage />} />
            <Route
              path='plataforma/:id/editar'
              element={<PlataformaFormPage />}
            />
            <Route path='ponto-coleta' element={<PontoColetaListPage />} />
            <Route path='ponto-coleta/novo' element={<PontoColetaFormPage />} />
            <Route
              path='ponto-coleta/:id/editar'
              element={<PontoColetaFormPage />}
            />
          </Route>

          <Route
            path='sistema'
            element={
              <ProtectedRoute requireAdmin={true}>
                <SistemaPage />
              </ProtectedRoute>
            }>
            <Route index element={<Navigate to='/sistema/usuarios' replace />} />
            <Route path='usuarios' element={<UsuarioListPage />} />
            <Route path='usuarios/novo' element={<UsuarioFormPage />} />
            <Route path='usuarios/:id/editar' element={<UsuarioFormPage />} />
            <Route path='setores' element={<SetorListPage />} />
            <Route path='setores/novo' element={<SetorFormPage />} />
            <Route path='setores/:id/editar' element={<SetorFormPage />} />
            <Route
              path='setores/:id/permissoes'
              element={<SetorPermissoesPage />}
            />
          </Route>

          <Route
            path='configuracoes'
            element={
              <ProtectedRoute requireAdmin={true}>
                <ConfiguracoesPage />
              </ProtectedRoute>
            }>
            <Route
              index
              element={<Navigate to='/configuracoes/producao' replace />}
            />
            <Route path='producao' element={<ConfiguracoesProducaoPage />} />
            <Route
              path='demanda-permissions'
              element={<PermissoesDemandaPage />}
            />
            <Route path='integracoes' element={<IntegracoesPage />}>
              <Route
                path='install/:moduleId'
                element={<InstallWizard />}
              />
            </Route>
            <Route path='roteamento' element={<IntegrationRoutingPage />} />
            <Route path='bling' element={<ConfiguracoesBlingPage />} />
          </Route>

          <Route
            path='relatorios'
            element={
              <ProtectedRoute requireAdmin={true}>
                <RelatoriosPage />
              </ProtectedRoute>
            }>
            <Route index element={<Navigate to='/relatorios/index' replace />} />
            <Route path='index' element={<RelatoriosIndexPage />} />
            <Route
              path='historico-producao'
              element={<HistoricoProducaoPage />}
            />
            <Route path='historico-coletas' element={<HistoricoColetasPage />} />
            <Route path='fila-estoque' element={<MonitoramentoEstoquePage />} />
            <Route path='monitoramento-estoque' element={<MonitoramentoEstoquePage />} />
            <Route path='monitoramento' element={<Navigate to='/relatorios/monitoramento-estoque' replace />} />
            <Route path='auditoria' element={<AuditoriaPage />} />
            <Route path='gerencial-historico' element={<GerencialHistorico />} />
          </Route>

          <Route
            path='ferramentas'
            element={
              <ProtectedRoute requireAdmin={true}>
                <FerramentasPage />
              </ProtectedRoute>
            }
          />
        </Route>
      </Routes>
      <Toaster />
    </>
  )
}

export default App
