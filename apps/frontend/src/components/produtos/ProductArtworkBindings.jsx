import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import LocalAgentService from '@/services/LocalAgentService'
import printArtworkService from '@/services/printArtworkService'

const ROLES = { capa: 'Capa', contra: 'Contra', miolo: 'Miolo' }

export default function ProductArtworkBindings({ productId, initialData }) {
  const [data, setData] = useState(initialData)
  const [mappings, setMappings] = useState({})
  const [printers, setPrinters] = useState([])
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [selection, setSelection] = useState({})
  const [printerByArt, setPrinterByArt] = useState({})
  const [busy, setBusy] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const allComponents = data?.componentes || []
  const candidates = allComponents.filter((item) => showAll || item.papel_sugerido ||
    (data?.artes || []).some((art) => art.componentes?.some((link) => Number(link.componente_id) === Number(item.componente_id))))

  const refresh = useCallback(async () => {
    try {
      setData(await printArtworkService.get(productId))
      const local = await Promise.allSettled([LocalAgentService.getMappings(), LocalAgentService.getPrinters()])
      if (local[0].status === 'fulfilled') setMappings(local[0].value.mappings || {})
      if (local[1].status === 'fulfilled') setPrinters(local[1].value.printers || [])
    } catch (error) {
      toast.error(error.message)
    }
  }, [productId])

  useEffect(() => { refresh() }, [refresh])

  const start = (art = null) => {
    setEditing(art?.id || 'new')
    setName(art?.nome || '')
    setSelection(Object.fromEntries((art?.componentes || []).map((item) => [item.componente_id, item.papel])))
  }

  const save = async () => {
    const components = Object.entries(selection).filter(([, role]) => role)
      .map(([id, papel]) => ({ componente_id: Number(id), papel }))
    if (!name.trim() || !components.length) {
      toast.warning('Informe o nome da arte e marque ao menos um componente.')
      return
    }
    setBusy(true)
    try {
      const payload = { nome: name.trim(), componentes: components }
      if (editing === 'new') await printArtworkService.create(productId, payload)
      else await printArtworkService.update(productId, editing, payload)
      setEditing(null)
      await refresh()
      toast.success('Arte salva. Associe o PDF nesta máquina.')
    } catch (error) {
      toast.error(error.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (art) => {
    if (!window.confirm('Excluir a arte ' + art.nome + '? O histórico continuará disponível.')) return
    setBusy(true)
    try {
      await printArtworkService.remove(productId, art.id)
      await refresh()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setBusy(false)
    }
  }

  const saveLocal = async (art, path = null, printerOverride = null) => {
    const current = mappings['arte:' + art.id]
    const filePath = path || current?.file_path
    const printer = printerByArt[art.id] || printerOverride || current?.printer_name
    if (!filePath || !printer) {
      toast.warning('Selecione o PDF e uma impressora.')
      return
    }
    setBusy(true)
    try {
      await LocalAgentService.saveMapping({
        artwork_id: art.id, product_id: productId, file_path: filePath, printer_name: printer,
      })
      await refresh()
      toast.success('PDF e impressora associados nesta máquina.')
    } catch (error) {
      toast.error(error.response?.data?.error || error.message)
    } finally {
      setBusy(false)
    }
  }

  const selectPdf = async (art) => {
    try {
      const selected = await LocalAgentService.mapFile('', art.id)
      if (selected.file_path) await saveLocal(art, selected.file_path)
    } catch (error) {
      toast.error(error.response?.data?.error || error.message)
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="text-xl font-semibold">Artes do produto final</h2><p className="text-sm text-muted-foreground">Um PDF pode atender vários componentes. Arquivo e impressora ficam nesta máquina.</p></div>
        <div className="flex gap-2"><Button type="button" variant="outline" size="sm" onClick={refresh}>Atualizar</Button><Button type="button" size="sm" onClick={() => start()}>Nova arte</Button></div>
      </div>
      {(data?.artes || []).map((art) => {
        const mapping = mappings['arte:' + art.id]
        const legacy = (art.componentes || []).map((link) => candidates.find((item) => Number(item.componente_id) === Number(link.componente_id)))
          .map((item) => item && mappings[item.sku]).find(Boolean)
        return <div key={art.id} className="space-y-3 rounded-lg border p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><div className="font-medium">{art.nome}</div>
              <div className="mt-1 text-sm text-muted-foreground">{(art.componentes || []).map((link) => ROLES[link.papel] + ': ' + (candidates.find((item) => Number(item.componente_id) === Number(link.componente_id))?.nome || link.componente_id)).join(' · ')}</div>
              <div className="mt-1 text-xs text-muted-foreground">{mapping?.file_path || 'PDF não associado nesta máquina'}</div>
            </div>
            <div className="flex gap-1"><Button type="button" size="sm" variant="outline" onClick={() => start(art)}>Editar</Button><Button type="button" size="sm" variant="outline" onClick={() => remove(art)} disabled={busy}>Excluir</Button></div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label={'Impressora para ' + art.nome} className="h-9 min-w-[190px] rounded-md border bg-background px-2 text-sm" value={printerByArt[art.id] ?? mapping?.printer_name ?? ''} onChange={(event) => setPrinterByArt((current) => ({ ...current, [art.id]: event.target.value }))}>
              <option value="">Impressora...</option>{mapping?.printer_name && !printers.includes(mapping.printer_name) && <option value={mapping.printer_name}>{mapping.printer_name} (indisponível)</option>}
              {printers.map((printer) => <option key={printer} value={printer}>{printer}</option>)}
            </select>
            {mapping && <Button type="button" size="sm" variant="outline" onClick={() => saveLocal(art)} disabled={busy}>Salvar impressora</Button>}
            <Button type="button" size="sm" variant="outline" onClick={() => selectPdf(art)} disabled={busy}>{mapping ? 'Substituir PDF' : 'Associar PDF'}</Button>
            {!mapping && legacy && <Button type="button" size="sm" variant="ghost" onClick={() => saveLocal(art, legacy.file_path, legacy.printer_name)} disabled={busy}>Usar PDF da capa</Button>}
          </div>
        </div>
      })}
      {editing && <div className="space-y-3 rounded-lg border border-primary/40 bg-muted/20 p-4">
        <label className="block text-sm font-medium">Nome da arte<Input className="mt-1" value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex.: Capa e contracapa" maxLength={160} /></label>
        <div className="text-sm font-medium">Componentes atendidos pelo mesmo PDF</div>
        <button type="button" className="text-left text-xs text-primary underline" onClick={() => setShowAll((value) => !value)}>{showAll ? 'Mostrar apenas capa, contra e miolo' : 'Mostrar todos os componentes da ficha'}</button>
        <div className="grid gap-2 sm:grid-cols-2">{candidates.map((component) => {
          const other = (data?.artes || []).find((art) => art.id !== editing && art.componentes?.some((link) => Number(link.componente_id) === Number(component.componente_id)))
          return <label key={component.componente_id} className="flex items-center gap-2 rounded-md border bg-background p-2 text-sm">
            <input type="checkbox" checked={Boolean(selection[component.componente_id])} disabled={Boolean(other)} onChange={(event) => setSelection((current) => ({ ...current, [component.componente_id]: event.target.checked ? (component.papel_sugerido || 'capa') : null }))} />
            <span className="min-w-0 flex-1">{component.nome} <span className="text-muted-foreground">({component.quantidade} por produto)</span>{other && <span className="text-amber-700"> · {other.nome}</span>}</span>
            {selection[component.componente_id] && <select aria-label={'Papel de ' + component.nome} value={selection[component.componente_id]} onChange={(event) => setSelection((current) => ({ ...current, [component.componente_id]: event.target.value }))}>{Object.entries(ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>}
          </label>
        })}</div>
        <div className="flex gap-2"><Button type="button" size="sm" onClick={save} disabled={busy}>Salvar arte</Button><Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancelar</Button></div>
      </div>}
      {!editing && !(data?.artes || []).length && <p className="rounded-lg border p-4 text-sm text-muted-foreground">Cadastre a primeira arte e marque os componentes que o PDF imprime.</p>}
    </section>
  )
}
