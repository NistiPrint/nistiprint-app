import { useSearchParams } from 'react-router-dom'
import CapaPrintPlanner from '@/components/producao/CapaPrintPlanner'

export default function PlanoImpressaoPage() {
  const [params] = useSearchParams()
  const planId = params.get('plano_id')
  if (!planId) return <main className="p-6 text-sm text-muted-foreground">Plano de impressão não informado.</main>
  return <CapaPrintPlanner planId={planId} standalone />
}
