import React, { useState, useEffect } from 'react';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const EditableCell = ({
  value: initialValue,
  onSave,
  isEditable,
  type = 'text', // 'text', 'number', 'time', 'select', 'textarea'
  options = [], // for type 'select'
  className = ''
}) => {
  const [value, setValue] = useState(initialValue);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue]);

  const handleBlur = () => {
    setIsEditing(false);
    if (value !== initialValue) {
      onSave(value);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault(); // Prevent new line in textarea
      setIsEditing(false);
      if (value !== initialValue) {
        onSave(value);
      }
    } else if (e.key === 'Escape') {
      setIsEditing(false);
      setValue(initialValue); // Revert changes
    }
  };

  const renderInput = () => {
    switch (type) {
      case 'number':
        return (
          <Input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            autoFocus
            className="p-1 h-auto text-sm"
          />
        );
      case 'time':
        return (
          <Input
            type="time"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            autoFocus
            className="p-1 h-auto text-sm"
          />
        );
      case 'select':
        return (
          <Select value={value} onValueChange={(selectedValue) => {
            setValue(selectedValue);
            setIsEditing(false); // Close select after change
            onSave(selectedValue); // Save immediately on select change
          }}>
            <SelectTrigger className="p-1 h-auto text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        );
      case 'textarea':
        return (
          <Textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            autoFocus
            className="p-1 h-auto text-sm resize-none"
            rows={2}
          />
        );
      case 'text':
      default:
        return (
          <Input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            autoFocus
            className="p-1 h-auto text-sm"
          />
        );
    }
  };

  return (
    <div className={`editable-cell ${className}`} onClick={() => isEditable && setIsEditing(true)}>
      {isEditing && isEditable ? (
        renderInput()
      ) : (
        <span className={isEditable ? 'cursor-pointer hover:bg-gray-100 rounded px-1 -mx-1' : ''}>
          {type === 'select' ? (options.find(opt => opt.value === initialValue)?.label || initialValue) : initialValue || '-'}
        </span>
      )}
    </div>
  );
};

export default EditableCell;
