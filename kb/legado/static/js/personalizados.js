// Global variables
let currentChatUsername = '';
let currentOrderNumber = '';

// Toggle chat sidebar visibility
function toggleSidebar() {
  const drawerRight = document.getElementById('drawerRight');
  const chatOverlay = document.getElementById('chatOverlay');

  const isOpen = drawerRight.style.right === '0px';
  drawerRight.style.right = isOpen ? '-250px' : '0px';
  chatOverlay.style.opacity = isOpen ? '0' : '1';
  chatOverlay.style.visibility = isOpen ? 'hidden' : 'visible';

  if (isOpen) {
    // Clear messages when closing sidebar
    const chatMessagesContainer = document.getElementById('chatMessages');
    if (chatMessagesContainer) {
      chatMessagesContainer.innerHTML = '<p style="text-align: center; color: #6c757d;">Conteúdo do chat irá aparecer aqui.</p>';
    }
    const chatOrderIdElement = document.getElementById('chatOrderId');
    if (chatOrderIdElement) {
      chatOrderIdElement.textContent = '';
    }
  }
}

// Function to show chat
function openChat(buttonElement) {
    console.log('openChat called');
    const username = buttonElement.dataset.username;
    const orderCard = buttonElement.closest('.order-card');
    const orderId = orderCard ? orderCard.dataset.orderId : 'N/A';

    // Get personalization message IDs from the order data
    const orderData = JSON.parse(orderCard.getAttribute('data-order-json') || '{}');
    const personalizationMessageIds = [];

    if (orderData.itens) {
      orderData.itens.forEach(item => {
        if (item.personalizations) {
          item.personalizations.forEach(p => {
            if (p.name_source_message_id) personalizationMessageIds.push(p.name_source_message_id);
            if (p.initial_source_message_id) personalizationMessageIds.push(p.initial_source_message_id);
          });
        }
      });
    }

    if (username) {
      const chatOrderIdElement = document.getElementById('chatOrderId');
      if (chatOrderIdElement) {
        chatOrderIdElement.textContent = `Pedido #${orderId} - ${username}`;
      }

      // Store the personalization message IDs in a data attribute for use in loadMessages
      const chatSidebar = document.getElementById('chatSidebar');
      if (chatSidebar) {
        chatSidebar.setAttribute('data-highlight-messages', JSON.stringify(personalizationMessageIds));
      }

      loadMessages(username);
      toggleSidebar();
    } else {
      console.error('Username not found for this order.');
    }
}

// Format message date
function formatMessageDate(timestamp) {
  if (!timestamp) return '';

  const date = new Date(timestamp);
  const now = new Date();
  const diffInDays = Math.floor((now - date) / (1000 * 60 * 60 * 24));

  if (diffInDays === 0) {
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } else if (diffInDays === 1) {
    return 'Ontem ' + date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } else if (diffInDays < 7) {
    return date.toLocaleDateString('pt-BR', { weekday: 'long' }) + ' ' +
           date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } else {
    return date.toLocaleDateString('pt-BR') + ' ' +
           date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }
}

// Function to render message content
function renderMessageContent(message) {
  if (!message) return '';

  // Use display_content if available, otherwise fall back to content
  const content = message.display_content || message.content || '';

  // Replace newlines with <br>
  let formatted = content.replace(/\n/g, '<br>');

  // Make URLs clickable
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  formatted = formatted.replace(urlRegex, url => {
    return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
  });

  return formatted;
}

// Function to render a single message
function renderMessage(message, username) {
  const isNotification = message.type === 'notification';
  const isBundle = message.type === 'bundle_message';
  const isSent = message.from_user_name === username;
  const messageClass = isNotification ? 'notification' : (isBundle ? 'bundle-message' : (isSent ? 'received' : 'sent'));

  const messageDate = new Date(message.created_at + 'Z');
  const now = new Date();
  const fourDaysAgo = new Date(now);
  fourDaysAgo.setDate(now.getDate() - 4);
  const isOld = messageDate < fourDaysAgo;
  const oldClass = isOld ? ' old-message' : '';

  const time = formatMessageDate(messageDate);

  // Handle bundle messages
  if (isBundle && message.bundle_messages && message.bundle_messages.length > 0) {
    let bundleHtml = `
      <div class="bundle-header">
        <i class="fas fa-layer-group me-1"></i> Mensagens agrupadas
      </div>
      <div class="bundle-content">
    `;

    // Add each message in the bundle
    message.bundle_messages.forEach(bundleMsg => {
      const bundleIsSent = bundleMsg.from_user_name === username;
      const bundleMessageClass = bundleIsSent ? 'received' : 'sent';
      const bundleContent = renderMessageContent(bundleMsg);
      const bundleTime = bundleMsg.created_at ? formatMessageDate(new Date(bundleMsg.created_at + 'Z')) : '';

      bundleHtml += `
        <div class="message ${bundleMessageClass}">
          <div>${bundleContent}</div>
          ${bundleTime ? `<div class="message-time">${bundleTime}</div>` : ''}
        </div>
      `;
    });

    bundleHtml += `</div>`;

    return `
      <div class="message ${messageClass}${oldClass}">
        ${bundleHtml}
        <div class="message-time">${time}</div>
      </div>
    `;
  }

  // Regular message
  const messageText = renderMessageContent(message);

  return `
    <div class="message ${messageClass}${oldClass}">
      <div>${messageText}</div>
      <div class="message-time">
        ${time}
        ${isOld ? ' <i class="fas fa-exclamation-triangle text-warning" title="Mensagem antiga"></i>' : ''}
      </div>
    </div>
  `;
}

// Function to load chat messages
async function loadMessages(username) {
  const messagesContainer = document.getElementById('chatMessages');
  if (!messagesContainer) return;

  // Show loading
  messagesContainer.innerHTML = '<div class="text-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden"></span></div></div>';

  try {
    const response = await fetch(`/api/personalizados/messages/${encodeURIComponent(username)}`);
    if (!response.ok) {
      throw new Error(`Erro ao carregar mensagens: ${response.status}`);
    }

    const messages = await response.json();

    if (!Array.isArray(messages) || messages.length === 0) {
      messagesContainer.innerHTML = `
        <div class="text-center p-4 text-muted">
          <i class="fas fa-comment-slash fa-2x mb-2"></i>
          <p>Nenhuma mensagem encontrada</p>
        </div>`;
      return;
    }

    // Group messages by date
    const groupedMessages = groupMessagesByDate(messages);

    // Render messages
    let messagesHtml = '';
    Object.entries(groupedMessages).forEach(([date, msgs]) => {
      messagesHtml += `<div class="date-badge">${formatDateBadge(date)}</div>`;
      msgs.forEach(msg => {
        messagesHtml += renderMessage(msg, username);
      });
    });

    messagesContainer.innerHTML = messagesHtml;

    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

  } catch (error) {
    console.error('Error loading messages:', error);
    messagesContainer.innerHTML = `
      <div class="alert alert-danger">
        <strong>Erro ao carregar mensagens:</strong><br>
        ${error.message}
        ${window.location.hostname === 'localhost' ? `<br><small class="text-muted">${error.stack || ''}</small>` : ''}
      </div>`;
  }
}

// Group messages by date
function groupMessagesByDate(messages) {
  return messages.reduce((groups, message) => {
    const date = message.created_at.split('T')[0];
    if (!groups[date]) {
      groups[date] = [];
    }
    groups[date].push(message);
    return groups;
  }, {});
}

// Format date badge (e.g., "Hoje", "Ontem", or formatted date)
function formatDateBadge(dateString) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const date = new Date(dateString);
  const formattedDate = date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });

  if (date.toDateString() === today.toDateString()) {
    return 'Hoje';
  } else if (date.toDateString() === yesterday.toDateString()) {
    return 'Ontem';
  } else {
    return formattedDate;
  }
}

// Initialize event listeners when the DOM is fully loaded
document.addEventListener('DOMContentLoaded', function() {
  // Close sidebar when pressing Escape key
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
      const drawerRight = document.getElementById('drawerRight');
      const chatOverlay = document.getElementById('chatOverlay');

      if (drawerRight && drawerRight.style.right === '0px') {
        toggleSidebar();
      }
    }
  });
});
