import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import MarketplaceService from '@/services/MarketplaceService';
import { Download, Puzzle, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

const Marketplace = () => {
  const [modules, setModules] = useState([]);
  const [filteredModules, setFilteredModules] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetchModules();
  }, []);

  useEffect(() => {
    filterModules();
  }, [modules, searchTerm, selectedCategory]);

  const fetchModules = async () => {
    try {
      setLoading(true);
      const data = await MarketplaceService.getAvailableModules();
      setModules(data || []);
    } catch (error) {
      console.error('Error fetching modules:', error);
      toast.error("Erro ao carregar módulos do marketplace");
    } finally {
      setLoading(false);
    }
  };

  const filterModules = () => {
    let result = modules;

    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      result = result.filter(module => 
        module.name.toLowerCase().includes(term) ||
        module.description.toLowerCase().includes(term) ||
        module.tags.some(tag => tag.toLowerCase().includes(term))
      );
    }

    if (selectedCategory && selectedCategory !== 'all') {
      result = result.filter(module => module.category === selectedCategory);
    }

    setFilteredModules(result);
  };

  const categories = [...new Set(modules.map(module => module.category))];

  const handleInstallClick = (moduleId) => {
    navigate(`/configuracoes/integracoes/install/${moduleId}`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-muted/30 p-4 rounded-lg">
        <div className="relative w-full md:w-1/3">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Buscar integrações..."
            className="pl-9"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        
        <div className="w-full md:w-1/4">
          <Select value={selectedCategory} onValueChange={setSelectedCategory}>
            <SelectTrigger>
              <SelectValue placeholder="Categoria" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as categorias</SelectItem>
              {categories.map(category => (
                <SelectItem key={category} value={category}>{category}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center p-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      ) : filteredModules.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredModules.map(module => (
            <Card key={module.id} className="flex flex-col h-full hover:shadow-md transition-shadow">
              <CardHeader className="flex flex-row gap-4 items-start space-y-0">
                <div className="h-12 w-12 rounded-lg bg-muted flex items-center justify-center shrink-0 overflow-hidden">
                  {module.icon_url ? (
                    <img 
                      src={module.icon_url} 
                      alt={`${module.name} Icon`} 
                      className="h-full w-full object-contain"
                      onError={(e) => { e.target.style.display='none'; }} 
                    />
                  ) : (
                    <Puzzle className="h-6 w-6 text-muted-foreground" />
                  )}
                </div>
                <div className="flex-1 space-y-1">
                  <CardTitle className="text-lg">{module.name}</CardTitle>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {module.tags.slice(0, 3).map(tag => (
                      <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex-1">
                <CardDescription className="line-clamp-3">
                  {module.description}
                </CardDescription>
              </CardContent>
              <CardFooter className="flex justify-between items-center pt-0">
                <span className="text-xs text-muted-foreground">
                  v{module.version} • {module.author}
                </span>
                <Button size="sm" onClick={() => handleInstallClick(module.id)}>
                  <Download className="mr-2 h-4 w-4" />
                  Instalar
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="bg-muted/10 border-dashed">
          <CardContent className="flex flex-col items-center justify-center p-12 text-center">
            <Puzzle className="h-12 w-12 text-muted-foreground mb-4 opacity-50" />
            <h3 className="text-lg font-semibold">Nenhuma integração encontrada</h3>
            <p className="text-muted-foreground max-w-sm mt-2">
              Tente ajustar seus termos de busca ou filtros para encontrar o que procura.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default Marketplace;
