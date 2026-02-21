import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { PlusCircle, Trash2, Edit, Share2, CircleDotDashed, CircleCheck, CircleX } from 'lucide-react';
import { toast } from 'sonner';

function IntegracoesListPage() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAccounts = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/v2/integracoes/', {
        headers: { 'Accept': 'application/json' }
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      
      // Fetch status for each account
      const accountsWithStatus = await Promise.all((data.accounts || []).map(async (account) => {
        try {
          const statusResponse = await fetch(`/api/v2/integracoes/status/${account.id}`);
          const statusData = await statusResponse.json();
          return { ...account, status: statusData.status };
        } catch (statusError) {
          console.error(`Error fetching status for account ${account.id}:`, statusError);
          return { ...account, status: 'ERROR' }; // Default status on error
        }
      }));
      setAccounts(accountsWithStatus);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar integrações: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
  }, []);

  const getStatusIcon = (status) => {
    switch (status) {
      case 'VALID':
        return <CircleCheck className="h-4 w-4 text-green-500" />;
      case 'INVALID':
        return <CircleX className="h-4 w-4 text-red-500" />;
      case 'NO_TOKEN':
        return <CircleDotDashed className="h-4 w-4 text-yellow-500" />;
      default:
        return <CircleDotDashed className="h-4 w-4 text-gray-500" />;
    }
  };

  const handleDeleteAccount = async (accountId, accountName) => {
    if (!confirm(`Tem certeza que deseja deletar a integração "${accountName}"?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/v2/integracoes/${accountId}`, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      if (result.success) {
        toast.success(result.message);
        fetchAccounts(); // Refresh list
      } else {
        toast.error(result.error || 'Erro ao deletar integração.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    }
  };

  if (loading) return <div className="text-center py-4">Carregando Integrações...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Integrações</h1>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="flex items-center gap-2">
            <Share2 className="h-5 w-5" /> Integrações Bling
          </CardTitle>
          <Link to="/integracoes/new">
            <Button size="sm">
              <PlusCircle className="h-4 w-4 mr-2" /> Nova Integração
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          {accounts.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma integração encontrada.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Nome da Conta</TableHead>
                    <TableHead>CNPJ</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {accounts.map((account) => (
                    <TableRow key={account.id}>
                      <TableCell>{account.id}</TableCell>
                      <TableCell>{account.account_name}</TableCell>
                      <TableCell>{account.cnpj || 'N/A'}</TableCell>
                      <TableCell className="text-center flex items-center justify-center gap-1">
                        {getStatusIcon(account.status)} {account.status || 'N/A'}
                      </TableCell>
                      <TableCell className="text-right">
                        <Link to={`/integracoes/${account.id}/edit`}>
                          <Button variant="outline" size="sm" className="mr-2">
                            <Edit className="h-4 w-4" /> Editar
                          </Button>
                        </Link>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => handleDeleteAccount(account.id, account.account_name)}
                        >
                          <Trash2 className="h-4 w-4" /> Deletar
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default IntegracoesListPage;