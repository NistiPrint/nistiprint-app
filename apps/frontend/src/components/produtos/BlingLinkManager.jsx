import React, { useState, useEffect } from 'react';
import ProductService from '../../services/ProductService';
import BlingAccountService from '../../services/BlingAccountService';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Trash2, Link as LinkIcon, Search, Plus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger, SheetDescription } from '@/components/ui/sheet';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card } from '@/components/ui/card';

const BlingLinkManager = ({ productId, initialLinks = [], onUpdate }) => {
  const [links, setLinks] = useState(initialLinks);
  const [accounts, setAccounts] = useState([]);
  
  // Add Link State
  const [selectedAccount, setSelectedAccount] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isAdding, setIsAdding] = useState(false);

  useEffect(() => {
    setLinks(initialLinks);
  }, [initialLinks]);

  useEffect(() => {
    loadAccounts();
  }, []);

  const loadAccounts = async () => {
    try {
      const data = await BlingAccountService.getAll();
      setAccounts(data);
    } catch (error) {
      console.error("Error loading accounts:", error);
    }
  };

  const handleSearchBling = async () => {
    if (!selectedAccount) {
      toast.error("Selecione uma conta Bling.");
      return;
    }
    if (!searchTerm || searchTerm.length < 3) {
      toast.error("Digite pelo menos 3 caracteres.");
      return;
    }

    setIsSearching(true);
    try {
      const data = await ProductService.searchBlingProducts(selectedAccount, searchTerm);
      setSearchResults(data.results || []);
    } catch (error) {
      toast.error("Erro ao buscar produtos no Bling.");
    } finally {
      setIsSearching(false);
    }
  };

  const handleAddLink = async (blingProduct) => {
    setIsAdding(true);
    try {
      const payload = {
        bling_product_id: blingProduct.id,
        bling_sku: blingProduct.sku,
        bling_account_id: selectedAccount,
        bling_name: blingProduct.name
      };
      
      await ProductService.addBlingLink(productId, payload);
      toast.success("Vínculo adicionado!");
      if (onUpdate) onUpdate(); // Refresh parent
      
      // Update local state optimistically or re-fetch? Parent refresh is better.
      // But for now update local
      setLinks([...links, { ...payload, created_at: new Date().toISOString() }]);

    } catch (error) {
      toast.error(`Erro ao vincular: ${error.message}`);
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemoveLink = async (link) => {
    if (!confirm("Remover este vínculo?")) return;

    try {
      await ProductService.removeBlingLink(productId, link.bling_product_id, link.bling_account_id);
      toast.success("Vínculo removido.");
      setLinks(links.filter(l => !(l.bling_product_id === link.bling_product_id && l.bling_account_id === link.bling_account_id)));
      if (onUpdate) onUpdate();
    } catch (error) {
      toast.error(`Erro ao remover: ${error.message}`);
    }
  };

  if (!productId) return <div className="p-4 text-center text-muted-foreground">Salve o produto para gerenciar vínculos.</div>;

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">Integrações Bling</h3>
        <Sheet>
          <SheetTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" /> Adicionar Vínculo
            </Button>
          </SheetTrigger>
          <SheetContent className="w-[400px] sm:w-[540px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Vincular Produto Bling</SheetTitle>
              <SheetDescription>
                Busque um produto no Bling para vincular a este cadastro.
              </SheetDescription>
            </SheetHeader>
            
            <div className="py-6 space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Conta Bling</label>
                <Select value={selectedAccount} onValueChange={setSelectedAccount}>
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione a conta..." />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map(acc => (
                      <SelectItem key={acc.id} value={acc.id}>{acc.account_name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Buscar Produto</label>
                <div className="flex gap-2">
                  <Input 
                    placeholder="Nome ou SKU..." 
                    value={searchTerm} 
                    onChange={(e) => setSearchTerm(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearchBling()}
                  />
                  <Button onClick={handleSearchBling} disabled={isSearching}>
                    {isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  </Button>
                </div>
              </div>

              {searchResults.length > 0 && (
                <div className="space-y-2 mt-4">
                  <label className="text-sm font-medium">Resultados</label>
                  <div className="space-y-2">
                    {searchResults.map(prod => (
                      <Card key={prod.id} className="p-3 flex justify-between items-center hover:bg-accent">
                        <div className="overflow-hidden">
                          <div className="font-medium truncate">{prod.name}</div>
                          <div className="text-xs text-muted-foreground">SKU: {prod.sku}</div>
                        </div>
                        <Button 
                          size="sm" 
                          variant="secondary" 
                          onClick={() => handleAddLink(prod)}
                          disabled={isAdding || links.some(l => l.bling_product_id === String(prod.id))}
                        >
                          {links.some(l => l.bling_product_id === String(prod.id)) ? 'Vinculado' : 'Vincular'}
                        </Button>
                      </Card>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </SheetContent>
        </Sheet>
      </div>

      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Conta</TableHead>
              <TableHead>SKU Bling</TableHead>
              <TableHead>Nome Bling</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {links.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-6 text-muted-foreground">
                  Nenhum vínculo encontrado.
                </TableCell>
              </TableRow>
            ) : (
              links.map((link, idx) => {
                const accountName = accounts.find(a => a.id === link.bling_account_id)?.account_name || link.bling_account_id;
                return (
                  <TableRow key={`${link.bling_product_id}-${idx}`}>
                    <TableCell>{accountName}</TableCell>
                    <TableCell>{link.bling_sku}</TableCell>
                    <TableCell>{link.bling_name}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" onClick={() => handleRemoveLink(link)}>
                        <Trash2 className="h-4 w-4 text-red-600" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
};

export default BlingLinkManager;
