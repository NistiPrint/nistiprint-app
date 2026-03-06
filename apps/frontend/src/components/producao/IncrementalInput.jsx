import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Check } from 'lucide-react';
import { useEffect, useState } from 'react';

export default function IncrementalInput({
  currentValue,
  fieldName,
  itemId,
  onSave,
  disabled,
  maxValue,
  totalQuantity
}) {
  const [localValue, setLocalValue] = useState(currentValue);

  useEffect(() => {
    setLocalValue(currentValue);
  }, [currentValue]);

  const handleBlur = () => {
    if (disabled) return;

    const oldValue = parseInt(currentValue || 0);
    const newValue = parseInt(localValue || 0);
    const delta = newValue - oldValue;

    if (delta !== 0) {
      // Optimistically assume success, but callback handles api call
      onSave(itemId, fieldName, delta)
        .catch((err) => {
           console.error("Save failed", err);
           setLocalValue(currentValue); // Revert on error
        });
    }
  };

  const handleChange = (e) => {
    const value = e.target.value;
    const numValue = parseInt(value || 0);

    // Validar: só números positivos, e não maior que maxValue se definido
    if (value === '' || (numValue >= 0 && (!maxValue || numValue <= maxValue))) {
      setLocalValue(value);
    }
    // Se inválido, não atualiza o estado
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.target.blur();
    }
  };

  const handleFillTotal = () => {
    if (disabled || !totalQuantity) return;

    const newValue = totalQuantity;
    const oldValue = parseInt(currentValue || 0);
    const delta = newValue - oldValue;

    if (delta !== 0) {
      // Preenche o input com o valor total
      setLocalValue(newValue.toString());

      // Dispara o salvamento automaticamente
      onSave(itemId, fieldName, delta)
        .catch((err) => {
           console.error("Save failed", err);
           setLocalValue(currentValue); // Revert on error
        });
    }
  };

  if (disabled) {
    return <span className="text-gray-600 font-medium">{currentValue}</span>;
  }

  return (
    <div className="flex items-center gap-1 justify-center">
      <Input
        type="number"
        min="0"
        max={maxValue}
        value={localValue}
        onChange={handleChange}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        className="h-8 w-16 text-center"
      />
      {totalQuantity && totalQuantity > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={handleFillTotal}
          className="h-6 w-6 p-0 opacity-0 hover:opacity-100 transition-opacity hover:bg-green-100"
          title={`Preencher com total (${totalQuantity})`}
        >
          <Check className="h-3 w-3 text-green-600" />
        </Button>
      )}
    </div>
  );
}
