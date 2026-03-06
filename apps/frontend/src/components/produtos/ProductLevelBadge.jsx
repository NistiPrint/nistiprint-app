import React from 'react';
import { Badge } from '@/components/ui/badge';

export const ProductLevelBadge = ({ type }) => {
  let badgeClass = '';
  let text = '';

  switch (type) {
    case 'materia_prima':
      badgeClass = 'bg-blue-100 text-blue-800 hover:bg-blue-100';
      text = 'MP';
      break;
    case 'intermediario':
      badgeClass = 'bg-purple-100 text-purple-800 hover:bg-purple-100';
      text = 'PI';
      break;
    case 'produto_acabado':
      badgeClass = 'bg-green-100 text-green-800 hover:bg-green-100';
      text = 'PA';
      break;
    case 'servico':
      badgeClass = 'bg-gray-100 text-gray-800 hover:bg-gray-100';
      text = 'SV';
      break;
    default:
      badgeClass = 'bg-gray-100 text-gray-800 hover:bg-gray-100';
      text = 'N/A';
  }

  return (
    <Badge className={`text-xs px-2 py-1 rounded ${badgeClass}`}>
      {text}
    </Badge>
  );
};