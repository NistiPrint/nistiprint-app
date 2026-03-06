import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import CategoryService from '@/services/CategoryService'
import { zodResolver } from '@hookform/resolvers/zod'
import { Edit, Loader2, PlusCircle, Settings, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

const categoriaSchema = z.object({
  name: z.string().min(1, { message: 'Nome da categoria é obrigatório.' }),
  description: z.string().optional().nullable(),
  bling_category_id: z.string().optional().nullable(),
  parent_category_id: z.string().optional().nullable(),
  comercializavel: z.boolean().optional(),
  componente: z.boolean().optional(),
})

function CategoriaFormPage() {
  const { id: categoriaId } = useParams()
  const navigate = useNavigate()
  const [loadingInitialData, setLoadingInitialData] = useState(true)
  const [loadingSubmit, setLoadingSubmit] = useState(false)
  const [parentCategories, setParentCategories] = useState([])
  const [rules, setRules] = useState([])
  const [newRule, setNewRule] = useState({
    nome_grupo: '',
    categoria_componente_id: '',
    min_quantidade: 1,
    max_quantidade: 1,
  })
  const [isRulesModalOpen, setIsRulesModalOpen] = useState(false)

  const isEditing = !!categoriaId

  const form = useForm({
    resolver: zodResolver(categoriaSchema),
    defaultValues: {
      name: '',
      description: '',
      bling_category_id: '',
      parent_category_id: 'none',
      comercializavel: false,
      componente: false,
    },
  })

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true)
      try {
        const categoriesData = await CategoryService.getAll()

        setParentCategories(categoriesData || [])

        if (isEditing) {
          const [catResponse, rulesData] = await Promise.all([
            CategoryService.getById(categoriaId),
            CategoryService.getRules(categoriaId),
          ])

          const data = catResponse.categoria
          setRules(rulesData || [])

          form.reset({
            name: data.nome || '',
            description: data.descricao || '',
            bling_category_id: data.bling_category_id || '',
            parent_category_id: data.categoria_pai_id || 'none',
            comercializavel: data.comercializavel || false,
            componente: data.componente || false,
          })
        }
      } catch (error) {
        toast.error(`Erro ao carregar dados: ${error.message}`)
        navigate('..')
      } finally {
        setLoadingInitialData(false)
      }
    }
    fetchFormData()
  }, [categoriaId, navigate, form, isEditing])

  const onSubmit = async data => {
    setLoadingSubmit(true)
    try {
      const dataToSend = { ...data }
      if (dataToSend.parent_category_id === 'none')
        dataToSend.parent_category_id = null

      if (isEditing) {
        await CategoryService.update(categoriaId, dataToSend)
        toast.success('Categoria atualizada com sucesso!')
      } else {
        await CategoryService.create(dataToSend)
        toast.success('Categoria criada com sucesso!')
      }
      navigate('..')
    } catch (error) {
      toast.error(`Erro: ${error.message}`)
    } finally {
      setLoadingSubmit(false)
    }
  }

  const handleAddRule = async () => {
    if (!newRule.nome_grupo || !newRule.categoria_componente_id) {
      toast.error('Preencha o nome do grupo e selecione a categoria.')
      return
    }

    try {
      await CategoryService.addRule(categoriaId, newRule)
      toast.success('Regra adicionada!')
      const updatedRules = await CategoryService.getRules(categoriaId)
      setRules(updatedRules)
      setNewRule({
        nome_grupo: '',
        categoria_componente_id: '',
        min_quantidade: 1,
        max_quantidade: 1,
      })
    } catch (error) {
      toast.error(`Erro ao adicionar regra: ${error.message}`)
    }
  }

  const handleDeleteRule = async ruleId => {
    try {
      await CategoryService.deleteRule(ruleId)
      toast.success('Regra removida!')
      setRules(rules.filter(r => r.id !== ruleId))
    } catch (error) {
      toast.error(`Erro ao remover regra: ${error.message}`)
    }
  }

  if (loadingInitialData)
    return (
      <div className='text-center py-4 text-muted-foreground'>
        Carregando formulário...
      </div>
    )

  return (
    <div className='space-y-6'>
      <Card className='w-full max-w-4xl mx-auto'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            {isEditing ? (
              <Edit className='h-5 w-5' />
            ) : (
              <PlusCircle className='h-5 w-5' />
            )}
            {isEditing ? 'Editar Categoria' : 'Nova Categoria'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-6'>
              {/* Informações Básicas */}
              <div className='grid grid-cols-1 md:grid-cols-2 gap-6'>
                <FormField
                  control={form.control}
                  name='name'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Nome da Categoria *</FormLabel>
                      <FormControl>
                        <Input
                          placeholder='Nome da Categoria'
                          {...field}
                          value={field.value || ''}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name='bling_category_id'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>ID Categoria Bling</FormLabel>
                      <FormControl>
                        <Input
                          placeholder='ID da Categoria no Bling'
                          {...field}
                          value={field.value || ''}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name='description'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Descrição</FormLabel>
                    <FormControl>
                      <Input
                        placeholder='Descrição da Categoria'
                        {...field}
                        value={field.value || ''}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Relacionamentos */}
              <div className='grid grid-cols-1 md:grid-cols-2 gap-6'>
                <FormField
                  control={form.control}
                  name='parent_category_id'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Categoria Pai</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value || 'none'}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder='Nenhuma' />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value='none'>Nenhuma</SelectItem>
                          {parentCategories
                            .filter(cat => cat.id !== categoriaId)
                            .map(cat => (
                              <SelectItem
                                key={cat.id}
                                value={cat.id.toString()}>
                                {cat.nome}
                              </SelectItem>
                            ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className='space-y-4'>
                  <FormField
                    control={form.control}
                    name='comercializavel'
                    render={({ field }) => (
                      <FormItem className='flex flex-row items-center space-x-3 space-y-0'>
                        <FormControl>
                          <input
                            type='checkbox'
                            checked={field.value || false}
                            onChange={e => field.onChange(e.target.checked)}
                            className='h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary'
                          />
                        </FormControl>
                        <div className='space-y-1 leading-none'>
                          <FormLabel className='text-sm font-normal'>
                            Comercializável
                          </FormLabel>
                          <p className='text-xs text-muted-foreground'>
                            Produtos podem ser comercializados
                          </p>
                        </div>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name='componente'
                    render={({ field }) => (
                      <FormItem className='flex flex-row items-center space-x-3 space-y-0'>
                        <FormControl>
                          <input
                            type='checkbox'
                            checked={field.value || false}
                            onChange={e => field.onChange(e.target.checked)}
                            className='h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary'
                          />
                        </FormControl>
                        <div className='space-y-1 leading-none'>
                          <FormLabel className='text-sm font-normal'>
                            Componente
                          </FormLabel>
                          <p className='text-xs text-muted-foreground'>
                            Pode ser usado como componente
                          </p>
                        </div>
                      </FormItem>
                    )}
                  />
                </div>
              </div>

              {/* Ações */}
              <div className='flex flex-col sm:flex-row gap-4 pt-4'>
                <Button
                  type='button'
                  variant='outline'
                  onClick={() => navigate('..')}
                  className='flex-1'>
                  Cancelar
                </Button>
                {isEditing && (
                  <Dialog
                    open={isRulesModalOpen}
                    onOpenChange={setIsRulesModalOpen}>
                    <DialogTrigger asChild>
                      <Button
                        type='button'
                        variant='secondary'
                        className='flex-1'>
                        <Settings className='mr-2 h-4 w-4' />
                        Regras BOM
                        {rules.length > 0 && (
                          <span className='ml-2 text-xs bg-primary text-primary-foreground px-2 py-1 rounded-full'>
                            {rules.length}
                          </span>
                        )}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className='max-w-4xl max-h-[90vh] overflow-y-auto'>
                      <DialogHeader>
                        <DialogTitle className='flex items-center gap-2'>
                          <Settings className='h-5 w-5' />
                          Regras de Composição (BOM)
                          <span className='text-sm font-normal text-muted-foreground'>
                            ({rules.length}{' '}
                            {rules.length === 1 ? 'regra' : 'regras'})
                          </span>
                        </DialogTitle>
                      </DialogHeader>
                      <div className='space-y-6'>
                        {/* Tabela de Regras Existentes */}
                        <div className='rounded-md border'>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className='w-[200px]'>
                                  Grupo
                                </TableHead>
                                <TableHead>Categoria Componente</TableHead>
                                <TableHead className='w-[100px]'>Mín</TableHead>
                                <TableHead className='w-[100px]'>Máx</TableHead>
                                <TableHead className='w-[50px]'></TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {rules.map(rule => (
                                <TableRow key={rule.id}>
                                  <TableCell className='font-medium'>
                                    {rule.nome_grupo}
                                  </TableCell>
                                  <TableCell>
                                    {rule.categoria_componente_nome}
                                  </TableCell>
                                  <TableCell className='text-center'>
                                    {rule.min_quantidade}
                                  </TableCell>
                                  <TableCell className='text-center'>
                                    {rule.max_quantidade}
                                  </TableCell>
                                  <TableCell>
                                    <Button
                                      variant='ghost'
                                      size='sm'
                                      onClick={() => handleDeleteRule(rule.id)}
                                      className='text-destructive hover:text-destructive hover:bg-destructive/10'>
                                      <Trash2 className='h-4 w-4' />
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                              {rules.length === 0 && (
                                <TableRow>
                                  <TableCell
                                    colSpan={5}
                                    className='text-center text-muted-foreground py-8'>
                                    Nenhuma regra definida para esta categoria.
                                  </TableCell>
                                </TableRow>
                              )}
                            </TableBody>
                          </Table>
                        </div>

                        {/* Formulário para Nova Regra */}
                        <div className='border rounded-lg p-6 bg-muted/10 space-y-6'>
                          <div className='flex items-center gap-2'>
                            <PlusCircle className='h-5 w-5 text-primary' />
                            <h4 className='text-base font-medium'>
                              Adicionar Nova Regra
                            </h4>
                          </div>

                          <div className='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4'>
                            <div className='space-y-2'>
                              <label className='text-sm font-medium'>
                                Nome do Grupo
                              </label>
                              <Input
                                placeholder='Ex: Pães'
                                value={newRule.nome_grupo}
                                onChange={e =>
                                  setNewRule({
                                    ...newRule,
                                    nome_grupo: e.target.value,
                                  })
                                }
                              />
                            </div>
                            <div className='space-y-2'>
                              <label className='text-sm font-medium'>
                                Categoria Componente
                              </label>
                              <Select
                                onValueChange={val =>
                                  setNewRule({
                                    ...newRule,
                                    categoria_componente_id: val,
                                  })
                                }
                                value={newRule.categoria_componente_id}>
                                <SelectTrigger>
                                  <SelectValue placeholder='Selecione...' />
                                </SelectTrigger>
                                <SelectContent>
                                  {parentCategories.map(cat => (
                                    <SelectItem
                                      key={cat.id}
                                      value={cat.id.toString()}>
                                      {cat.nome}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className='space-y-2'>
                              <label className='text-sm font-medium'>
                                Quantidade Mínima
                              </label>
                              <Input
                                type='number'
                                min='1'
                                value={newRule.min_quantidade}
                                onChange={e =>
                                  setNewRule({
                                    ...newRule,
                                    min_quantidade:
                                      parseInt(e.target.value) || 1,
                                  })
                                }
                              />
                            </div>
                            <div className='space-y-2'>
                              <label className='text-sm font-medium'>
                                Quantidade Máxima
                              </label>
                              <Input
                                type='number'
                                min='1'
                                value={newRule.max_quantidade}
                                onChange={e =>
                                  setNewRule({
                                    ...newRule,
                                    max_quantidade:
                                      parseInt(e.target.value) || 1,
                                  })
                                }
                              />
                            </div>
                          </div>

                          <div className='flex justify-end'>
                            <Button
                              onClick={handleAddRule}
                              variant='default'
                              className='min-w-[140px]'>
                              <PlusCircle className='h-4 w-4 mr-2' />
                              Adicionar Regra
                            </Button>
                          </div>
                        </div>
                      </div>
                    </DialogContent>
                  </Dialog>
                )}
                <Button
                  type='submit'
                  disabled={loadingSubmit}
                  className='flex-1'>
                  {loadingSubmit && (
                    <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                  )}
                  Salvar Categoria
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  )
}

export default CategoriaFormPage
