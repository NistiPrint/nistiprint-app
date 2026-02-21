import React from 'react';

export const AIStatusBadge = ({ status }) => {
  const styles = {
    SUCCESS: 'bg-green-100 text-green-800',
    NEEDS_REVIEW: 'bg-yellow-100 text-yellow-800',
    NO_PERSONALIZATION_FOUND: 'bg-gray-100 text-gray-800',
    ERROR: 'bg-red-100 text-red-800',
    PROCESSING: 'bg-blue-100 text-blue-800'
  };

  const labels = {
    SUCCESS: 'Sucesso',
    NEEDS_REVIEW: 'Revisar',
    NO_PERSONALIZATION_FOUND: 'Sem Personalização',
    ERROR: 'Erro',
    PROCESSING: 'Processando'
  };

  const currentStyle = styles[status] || styles.NO_PERSONALIZATION_FOUND;
  const label = labels[status] || status;

  return (
    <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${currentStyle}`}>
      {label}
    </span>
  );
};
