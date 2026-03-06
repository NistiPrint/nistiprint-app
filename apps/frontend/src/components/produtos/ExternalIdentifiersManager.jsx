import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Plus, X } from 'lucide-react';
import { useState } from 'react';

export default function ExternalIdentifiersManager({ value = { skus: [], names: [], ids: [] }, onChange }) {
  const [skuInput, setSkuInput] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [idInput, setIdInput] = useState('');
  const [selectedType, setSelectedType] = useState('sku');

  // Ensure value has the correct structure
  const safeValue = {
    skus: value?.skus || [],
    names: value?.names || [],
    ids: value?.ids || []
  };

  const handleAdd = () => {
    let inputValue = '';
    let targetArray = [];

    switch (selectedType) {
      case 'sku':
        inputValue = skuInput.trim();
        targetArray = safeValue.skus;
        break;
      case 'name':
        inputValue = nameInput.trim();
        targetArray = safeValue.names;
        break;
      case 'id':
        inputValue = idInput.trim();
        targetArray = safeValue.ids;
        break;
    }

    if (inputValue && !targetArray.includes(inputValue)) {
      const newValue = {
        ...safeValue,
        [selectedType === 'sku' ? 'skus' : selectedType === 'name' ? 'names' : 'ids']:
          [...targetArray, inputValue]
      };
      onChange(newValue);

      // Clear the appropriate input
      if (selectedType === 'sku') setSkuInput('');
      else if (selectedType === 'name') setNameInput('');
      else setIdInput('');
    }
  };

  const handleRemove = (type, identifier) => {
    const newValue = {
      ...safeValue,
      [type]: safeValue[type].filter(item => item !== identifier)
    };
    onChange(newValue);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAdd();
    }
  };

  const totalIdentifiers = safeValue.skus.length + safeValue.names.length + safeValue.ids.length;

  return (
    <div className="space-y-4">
      <div className="text-sm text-muted-foreground mb-3">
        Configure múltiplos nomes e SKUs alternativos para este produto. Isso permite que o sistema identifique automaticamente este produto em planilhas de diferentes marketplaces.
      </div>

      {/* Input Section */}
      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <Select value={selectedType} onValueChange={setSelectedType}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sku">SKU Alternativo</SelectItem>
              <SelectItem value="name">Nome Alternativo</SelectItem>
              <SelectItem value="id">ID Externo</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1">
          <Input
            placeholder={
              selectedType === 'sku' ? 'Digite um SKU alternativo' :
              selectedType === 'name' ? 'Digite um nome alternativo' :
              'Digite um ID externo'
            }
            value={
              selectedType === 'sku' ? skuInput :
              selectedType === 'name' ? nameInput :
              idInput
            }
            onChange={(e) => {
              if (selectedType === 'sku') setSkuInput(e.target.value);
              else if (selectedType === 'name') setNameInput(e.target.value);
              else setIdInput(e.target.value);
            }}
            onKeyDown={handleKeyDown}
          />
        </div>
        <Button type="button" onClick={handleAdd} variant="secondary">
          <Plus className="h-4 w-4 mr-2" /> Adicionar
        </Button>
      </div>

      {/* Display Section */}
      <div className="space-y-3">
        {/* SKUs Alternativos */}
        {safeValue.skus.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-blue-700 mb-2">SKUs Alternativos</h4>
            <div className="flex flex-wrap gap-2">
              {safeValue.skus.map((sku, index) => (
                <Badge key={`sku-${index}`} variant="outline" className="pl-3 pr-1 py-1 text-sm flex items-center gap-1 bg-blue-50 border-blue-200">
                  <span className="text-blue-700">{sku}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-4 w-4 rounded-full hover:bg-red-100 hover:text-red-600 p-0"
                    onClick={() => handleRemove('skus', sku)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Nomes Alternativos */}
        {safeValue.names.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-green-700 mb-2">Nomes Alternativos</h4>
            <div className="flex flex-wrap gap-2">
              {safeValue.names.map((name, index) => (
                <Badge key={`name-${index}`} variant="outline" className="pl-3 pr-1 py-1 text-sm flex items-center gap-1 bg-green-50 border-green-200">
                  <span className="text-green-700">{name}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-4 w-4 rounded-full hover:bg-red-100 hover:text-red-600 p-0"
                    onClick={() => handleRemove('names', name)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* IDs Externos */}
        {safeValue.ids.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-purple-700 mb-2">IDs Externos</h4>
            <div className="flex flex-wrap gap-2">
              {safeValue.ids.map((id, index) => (
                <Badge key={`id-${index}`} variant="outline" className="pl-3 pr-1 py-1 text-sm flex items-center gap-1 bg-purple-50 border-purple-200">
                  <span className="text-purple-700">{id}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-4 w-4 rounded-full hover:bg-red-100 hover:text-red-600 p-0"
                    onClick={() => handleRemove('ids', id)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </Badge>
              ))}
            </div>
          </div>
        )}

        {totalIdentifiers === 0 && (
          <p className="text-sm text-muted-foreground italic">
            Nenhum identificador alternativo cadastrado. Adicione SKUs e nomes alternativos para facilitar a identificação automática em planilhas.
          </p>
        )}
      </div>

      <div className="text-xs text-muted-foreground border-t pt-3">
        <strong>Total de identificadores:</strong> {totalIdentifiers}<br />
        Exemplos: Use "Agenda A 2025" como nome alternativo, ou "SKU-SHOPEE-123" como SKU alternativo para facilitar a correspondência automática durante a importação de vendas.
      </div>
    </div>
  );
}
