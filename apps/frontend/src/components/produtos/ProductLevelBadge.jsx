import React from 'react';
import { Badge } from '@/components/ui/badge';

export const ProductLevelBadge = ({ type }) => {
  let badgeClass = '';
  let text = '';

  switch (type) {
    case 'materia_prima':
      badgeClass = 'bg-blue-50 text-blue-700 hover:bg-blue-50';
      text = 'MP';
      break;
    case 'intermediario':
      badgeClass = 'bg-purple-50 text-purple-700 hover:bg-purple-50';
      text = 'PI';
      break;
    case 'produto_acabado':
      badgeClass = 'bg-green-50 text-green-700 hover:bg-green-50';
      text = 'PA';
      break;
    case 'servico':
      badgeClass = 'bg-gray-50 text-gray-600 hover:bg-gray-50';
      text = 'SV';
      break;
    default:
      badgeClass = 'bg-gray-50 text-gray-600 hover:bg-gray-50';
      text = 'N/A';
  }

  return (
    <Badge className={`px-1.5 py-0 text-[10px] font-medium ${badgeClass}`}>
      {text}
    </Badge>
  );
};
