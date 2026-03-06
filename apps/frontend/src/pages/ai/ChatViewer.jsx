import React, { useEffect, useRef } from 'react';
import { format } from 'date-fns';

export const ChatViewer = ({ messages, isOpen, onClose, title }) => {
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
    }
  }, [messages, isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-xl transform transition-transform duration-300 ease-in-out z-50 flex flex-col">
      <div className="p-4 border-b flex justify-between items-center bg-gray-50">
        <h3 className="font-semibold text-gray-700">{title}</h3>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-100">
        {messages.length === 0 ? (
          <p className="text-center text-gray-500 mt-10">Nenhuma mensagem encontrada.</p>
        ) : (
          messages.map((msg) => (
            <div 
              key={msg.id} 
              className={`flex flex-col ${msg.is_sender ? 'items-end' : 'items-start'}`}
            >
               <div 
                className={`max-w-[85%] rounded-lg p-3 ${
                  msg.is_sender 
                    ? 'bg-blue-500 text-white rounded-br-none' 
                    : 'bg-white text-gray-800 border border-gray-200 rounded-bl-none'
                }`}
              >
                {/* Tenta renderizar texto ou JSON content */}
                <p className="text-sm whitespace-pre-wrap">
                  {typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content)}
                </p>
              </div>
              <span className="text-xs text-gray-500 mt-1">
                {msg.created_at ? format(new Date(msg.created_at), 'dd/MM HH:mm') : ''}
              </span>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};
