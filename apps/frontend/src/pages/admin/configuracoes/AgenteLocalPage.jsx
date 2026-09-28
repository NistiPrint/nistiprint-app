import { useEffect, useState } from 'react';
import { Download, Monitor, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import LocalAgentService from '@/services/LocalAgentService';

const RELEASES = '/api/v2/local-agent/releases';

export default function AgenteLocalPage() {
  useSecaoSidebar();
  const [release, setRelease] = useState(null);
  const [agent, setAgent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${RELEASES}/latest.json`, { cache: 'no-store' });
      if (!response.ok) throw new Error('Nenhuma versão do agente foi publicada no servidor.');
      const manifest = await response.json();
      if (!/^\d+\.\d+\.\d+$/.test(manifest.version) || !/^[a-f\d]{64}$/i.test(manifest.sha256)) {
        throw new Error('Os dados da versão publicada estão inválidos.');
      }
      setRelease(manifest);
      setError(null);
    } catch (cause) {
      setRelease(null);
      setError(cause.message || 'Não foi possível consultar a versão disponível.');
    } finally {
      setLoading(false);
    }
    LocalAgentService.checkHealth().then(setAgent).catch(() => setAgent(null));
  };

  useEffect(() => { refresh(); }, []);

  const downloadUrl = release && `${RELEASES}/NistiPrintAgent-${release.version}.exe`;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Agente local</h1>
        <p className="text-muted-foreground">Instale o agente no computador Windows que acessa as impressoras e os arquivos locais.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Download className="h-5 w-5" /> Download para Windows</CardTitle>
          <CardDescription>{release ? `Versão disponível: ${release.version}` : 'Versão disponível no servidor NistiPrint'}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && <p role="status" className="text-sm text-amber-700">{error}</p>}
          <div className="flex flex-wrap gap-3">
            {downloadUrl && <Button asChild><a href={downloadUrl} download>Baixar agente</a></Button>}
            <Button variant="outline" onClick={refresh} disabled={loading}>
              <RefreshCw className="mr-2 h-4 w-4" /> {loading ? 'Consultando...' : 'Verificar versão'}
            </Button>
          </div>
          {release && <p className="break-all text-xs text-muted-foreground">SHA-256: {release.sha256}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Monitor className="h-5 w-5" /> Neste computador</CardTitle>
          <CardDescription>{agent ? `Agente online, versão ${agent.version || 'anterior'}` : 'Agente não detectado'}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>1. Baixe o arquivo e coloque o EXE em uma pasta em que seu usuário possa gravar, por exemplo, Documentos\NistiPrint.</p>
          <p>2. Execute o EXE. O ícone NistiPrint aparecerá na bandeja do Windows.</p>
          <p>3. Para iniciar junto com o Windows, crie um atalho para o EXE na pasta de Inicialização do seu usuário.</p>
          <p>As próximas versões poderão ser instaladas pelo aviso na aplicação ou pelo menu da bandeja.</p>
        </CardContent>
      </Card>
    </div>
  );
}
