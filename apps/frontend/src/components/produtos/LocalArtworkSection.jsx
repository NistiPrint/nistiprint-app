import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Printer, Upload, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import LocalAgentService from '@/services/LocalAgentService'
import ProductService from '@/services/ProductService'

function LocalArtworkSection({ productId, product, categories = [] }) {
  const [loading, setLoading] = useState(false)
  const [printers, setPrinters] = useState([])
  const [directMapping, setDirectMapping] = useState(null)
  const [components, setComponents] = useState([])
  const [mappings, setMappings] = useState({})
  const [copies, setCopies] = useState(1)
  const [selectedPrinter, setSelectedPrinter] = useState('')
  const [componentPrinters, setComponentPrinters] = useState({})

  const productCategory = categories.find(category => String(category.id) === String(product?.categoria_id))
  const categoryAllowsArtwork = Boolean(product?.permite_arte || productCategory?.permite_arte)
  const sku = product?.sku || ''

  const loadLocalData = async () => {
    if (!productId) return
    setLoading(true)
    try {
      const [{ printers: availablePrinters }, { mappings: availableMappings }] = await Promise.all([
        LocalAgentService.getPrinters(),
        LocalAgentService.getMappings(),
      ])
      setPrinters(availablePrinters || [])
      setMappings(availableMappings || {})
      const printerSelections = Object.fromEntries(
        Object.entries(availableMappings || {}).map(([mappingSku, mapping]) => [mappingSku, mapping.printer_name || '']),
      )
      setComponentPrinters(printerSelections)

      if (categoryAllowsArtwork && sku) {
        setDirectMapping(availableMappings?.[sku] || null)
        setSelectedPrinter(availableMappings?.[sku]?.printer_name || '')
      } else {
        const response = await ProductService.getRecursiveArtworks(productId)
        setComponents(response.artes || [])
      }
    } catch (error) {
      toast.error(`Não foi possível carregar as artes locais: ${error.message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLocalData()
  }, [productId, sku, categoryAllowsArtwork])

  const selectAndSave = async (targetSku, productIdForMapping, currentPrinter = '') => {
    const selected = await LocalAgentService.mapFile(targetSku)
    if (!selected.file_path) return
    const printerName = currentPrinter || selectedPrinter || printers[0]
    if (!printerName) throw new Error('Nenhuma impressora local foi encontrada.')
    await LocalAgentService.saveMapping({
      sku: targetSku,
      product_id: productIdForMapping,
      file_path: selected.file_path,
      printer_name: printerName,
    })
    await loadLocalData()
    toast.success('Arte local associada.')
  }

  const savePrinter = async () => {
    if (!directMapping || !selectedPrinter) {
      toast.error('Selecione uma impressora.')
      return
    }
    setLoading(true)
    try {
      await LocalAgentService.saveMapping({ ...directMapping, printer_name: selectedPrinter })
      await loadLocalData()
      toast.success('Impressora atualizada.')
    } catch (error) {
      toast.error(`Não foi possível atualizar a impressora: ${error.message}`)
    } finally {
      setLoading(false)
    }
  }

  const print = async (targetSku) => {
    const result = await LocalAgentService.printFile(targetSku, copies)
    if (result.status === 'file_opened') {
      toast.warning('A impressão direta falhou. O arquivo foi aberto para impressão manual.')
    } else {
      toast.success('Arquivo enviado para impressão local.')
    }
  }

  const saveComponentPrinter = async (component, mapping) => {
    const printerName = componentPrinters[component.sku]
    if (!mapping || !printerName) {
      toast.error('Selecione uma impressora.')
      return
    }
    try {
      await LocalAgentService.saveMapping({ ...mapping, printer_name: printerName })
      await loadLocalData()
      toast.success('Impressora atualizada.')
    } catch (error) {
      toast.error(`Não foi possível atualizar a impressora: ${error.message}`)
    }
  }

  if (!productId) {
    return <p className='text-sm text-muted-foreground'>Salve o produto antes de configurar sua arte local.</p>
  }

  return (
    <section className='space-y-5'>
      <div className='flex items-start justify-between gap-4'>
        <div>
          <h2 className='text-xl font-semibold'>Artes para impressão</h2>
          <p className='text-sm text-muted-foreground'>Arquivos brutos mantidos na máquina local, associados a uma impressora.</p>
        </div>
        <Button variant='outline' size='sm' onClick={loadLocalData} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Atualizar
        </Button>
      </div>

      {categoryAllowsArtwork ? (
        <div className='rounded-lg border p-4 space-y-4'>
          <div className='flex items-center justify-between gap-3'>
            <div>
              <p className='font-medium'>{product?.name || product?.nome}</p>
              <p className='text-sm text-muted-foreground'>SKU: {sku}</p>
            </div>
            <Badge variant={directMapping ? 'default' : 'secondary'}>{directMapping ? 'Configurada' : 'Não configurada'}</Badge>
          </div>
          {directMapping && <p className='text-sm truncate' title={directMapping.file_path}>{directMapping.file_path}</p>}
          <div className='flex flex-wrap items-end gap-3'>
            <div className='min-w-[240px] flex-1'>
              <Label htmlFor='local-printer'>Impressora</Label>
              <select id='local-printer' className='flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm' value={selectedPrinter} onChange={event => setSelectedPrinter(event.target.value)} disabled={loading}>
                <option value=''>Selecione...</option>
                {selectedPrinter && !printers.includes(selectedPrinter) && <option value={selectedPrinter}>{selectedPrinter} (não encontrada)</option>}
                {printers.map(printer => <option key={printer} value={printer}>{printer}</option>)}
              </select>
            </div>
            {directMapping && <Button variant='outline' onClick={savePrinter} disabled={loading || !selectedPrinter}>Salvar impressora</Button>}
            <Button onClick={() => selectAndSave(sku, productId, selectedPrinter)} disabled={loading || !sku || !selectedPrinter}>
              <Upload className='mr-2 h-4 w-4' /> {directMapping ? 'Substituir arquivo' : 'Associar arquivo'}
            </Button>
            <Input className='w-24' type='number' min='1' value={copies} onChange={event => setCopies(Math.max(1, Number(event.target.value) || 1))} />
            <Button onClick={() => print(sku)} disabled={loading || !directMapping}>
              <Printer className='mr-2 h-4 w-4' /> Imprimir
            </Button>
          </div>
        </div>
      ) : (
        <div className='space-y-3'>
          <p className='text-sm text-muted-foreground'>Artes dos componentes elegíveis da ficha técnica:</p>
          {components.length === 0 && <p className='rounded-lg border p-4 text-sm text-muted-foreground'>Nenhum componente com categoria que permita arte foi encontrado.</p>}
          {components.map(component => {
            const mapping = mappings[component.sku]
            return <div key={component.product_id} className='rounded-lg border p-4'>
              <div className='flex flex-wrap items-center justify-between gap-3'>
                <div>
                  <p className='font-medium'>{component.name}</p>
                  <p className='text-sm text-muted-foreground'>{component.category_name} · SKU: {component.sku}</p>
                </div>
                <Badge variant={mapping ? 'default' : 'secondary'}>{mapping ? 'Configurada' : 'Não configurada'}</Badge>
              </div>
              {mapping && <p className='mt-2 text-sm truncate' title={mapping.file_path}>{mapping.file_path}</p>}
              <div className='mt-3 flex flex-wrap items-end gap-2'>
                <div className='min-w-[240px] flex-1'>
                  <Label htmlFor={`printer-${component.product_id}`}>Impressora</Label>
                  <select
                    id={`printer-${component.product_id}`}
                    className='flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm'
                    value={componentPrinters[component.sku] || ''}
                    onChange={event => setComponentPrinters(current => ({ ...current, [component.sku]: event.target.value }))}
                    disabled={loading}
                  >
                    <option value=''>Selecione...</option>
                    {componentPrinters[component.sku] && !printers.includes(componentPrinters[component.sku]) && <option value={componentPrinters[component.sku]}>{componentPrinters[component.sku]} (não encontrada)</option>}
                    {printers.map(printer => <option key={printer} value={printer}>{printer}</option>)}
                  </select>
                </div>
                {mapping && <Button size='sm' variant='outline' onClick={() => saveComponentPrinter(component, mapping)} disabled={loading || !componentPrinters[component.sku]}>Salvar impressora</Button>}
                <Button size='sm' variant='outline' onClick={() => selectAndSave(component.sku, component.product_id, componentPrinters[component.sku])} disabled={loading || !componentPrinters[component.sku]}>
                  <Upload className='mr-2 h-4 w-4' /> {mapping ? 'Substituir' : 'Associar arquivo'}
                </Button>
                <Button size='sm' onClick={() => print(component.sku)} disabled={!mapping}>
                  <Printer className='mr-2 h-4 w-4' /> Imprimir
                </Button>
              </div>
            </div>
          })}
        </div>
      )}
    </section>
  )
}

export default LocalArtworkSection