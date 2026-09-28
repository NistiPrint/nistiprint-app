import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import LocalAgentService from '@/services/LocalAgentService';

export default function AgentUpdateBanner() {
  const [update, setUpdate] = useState(null);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = () => LocalAgentService.checkHealth()
      .then((health) => { if (active) setUpdate(health.update?.status === 'available' ? health.update : null); })
      .catch(() => { if (active) setUpdate(null); });
    refresh();
    const timer = setInterval(refresh, 60000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  if (!update) return null;

  const install = async () => {
    setInstalling(true);
    try {
      await LocalAgentService.installUpdate();
      setUpdate(null);
      toast.success('Atualização iniciada. O agente será reiniciado.');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Não foi possível atualizar o agente.');
    } finally {
      setInstalling(false);
    }
  };

  return (
    <div className="flex items-center justify-center gap-3 bg-blue-50 px-4 py-2 text-sm text-blue-950">
      <span>Nova versão do agente local: {update.available_version}</span>
      <Button size="sm" onClick={install} disabled={installing}>
        {installing ? 'Preparando...' : 'Atualizar agente'}
      </Button>
    </div>
  );
}
