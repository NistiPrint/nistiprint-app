import { Navigate, useParams } from 'react-router-dom';

/** Compatibility route: Mercado Livre settings now live in the shared account selector. */
export default function MercadoLivrePersonalizacaoConfigPage() {
  const { integration_id: integrationId } = useParams();
  const search = integrationId ? `?integration_id=${encodeURIComponent(integrationId)}` : '';
  return <Navigate to={`/configuracoes/ia${search}`} replace />;
}
