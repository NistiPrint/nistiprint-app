// Global variables
let currentChatUsername = '';
let currentOrderNumber = '';

// Toggle chat sidebar visibility
function toggleChatSidebar() {
  const chatSidebar = document.getElementById('chatSidebar');
  const chatOverlay = document.getElementById('chatOverlay');
  const isHidden = chatSidebar.style.transform === 'translateX(100%)' || !chatSidebar.style.transform;

  chatSidebar.style.transform = isHidden ? 'translateX(0)' : 'translateX(100%)';
  chatOverlay.style.opacity = isHidden ? '1' : '0';
  chatOverlay.style.visibility = isHidden ? 'visible' : 'hidden';
  document.body.style.overflow = isHidden ? 'hidden' : 'auto';
}

// Function to show chat
function showChat(orderId, username, orderNumber) {
    console.log('showChat called with:', { orderId, username, orderNumber });
    currentChatUsername = username;
    currentOrderNumber = orderNumber;

    // Update sidebar header
    const chatHeader = document.getElementById('chatHeader');
    if (chatHeader) {
        chatHeader.textContent = `Chat - Pedido ${orderNumber}`;
    }

    // Show the sidebar
    toggleChatSidebar();

    // Load messages
    loadChatMessages(username, orderNumber);
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

// Function to render a single message
function renderMessage(message) {
    const isOld = isMessageOld(message.created_at);
    const time = formatTime(message.created_at);
    const oldClass = isOld ? ' old-message' : '';

    // Handle different message types
    if (message.type === 'notification') {
        return `
            <div class="message notification">
                <div class="notification-content">${message.display_content}</div>
                <div class="message-time">${time}</div>
            </div>`;
    }

    if (message.bundle_messages && message.bundle_messages.length > 0) {
        // Bundle message
        const bundleItems = message.bundle_messages.map(item =>
            `<div class="bundle-item">${item.display_content}</div>`
        ).join('');

        return `
            <div class="message bundle">
                <div class="bundle-header">
                    <strong>${message.from_user_name || 'Usuário'}</strong>
                    <span class="badge bg-secondary">${message.bundle_messages.length + 1} mensagens</span>
                </div>
                <div class="bundle-content">
                    <div class="bundle-item">${message.display_content}</div>
                    ${bundleItems}
                </div>
                <div class="message-time">
                    ${time}
                    ${isOld ? ' <i class="fas fa-exclamation-triangle text-warning" title="Mensagem antiga"></i>' : ''}
                </div>
            </div>`;
    }

    // Regular message
    const messageClass = message.is_sent ? 'sent' : 'received';
    const messageText = renderMessageContent(message);

    return `
        <div class="message ${messageClass}${oldClass}">
            <div>${messageText}</div>
            <div class="message-time">
                ${time}
                ${isOld ? ' <i class="fas fa-exclamation-triangle text-warning" title="Mensagem antiga"></i>' : ''}
            </div>
        </div>`;
}

// Render message content with clickable links
function renderMessageContent(message) {
    // Convert URLs to clickable links
    return message.display_content.replace(
        /(https?:\/\/[^\s]+)/g,
        '<a href="$1" target="_blank" class="message-link">$1</a>'
    );
}

// Check if a message is old (older than 4 days)
function isMessageOld(dateString) {
    const messageDate = new Date(dateString);
    const fourDaysAgo = new Date();
    fourDaysAgo.setDate(fourDaysAgo.getDate() - 4);
    return messageDate < fourDaysAgo;
}

// Format time (e.g., "14:30")
function formatTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
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

// Load chat messages
async function loadChatMessages(username, orderNumber) {
    const messagesContainer = document.getElementById('chatMessages');
    const loadingIndicator = document.getElementById('chatLoading');
    const errorElement = document.getElementById('chatError');

    // Show loading, hide error
    loadingIndicator.style.display = 'block';
    errorElement.style.display = 'none';
    messagesContainer.innerHTML = '';

    try {
        const response = await fetch(`/api/messages/${username}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const messages = await response.json();

        if (messages.length === 0) {
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
        Object.entries(groupedMessages).forEach(([date, messages]) => {
            messagesHtml += `<div class="date-badge">${formatDateBadge(date)}</div>`;
            messages.forEach(message => {
                messagesHtml += renderMessage(message);
            });
        });

        messagesContainer.innerHTML = messagesHtml;

        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

    } catch (error) {
        console.error('Error loading messages:', error);
        errorElement.textContent = 'Erro ao carregar as mensagens. Tente novamente.';
        errorElement.style.display = 'block';
    } finally {
        loadingIndicator.style.display = 'none';
    }
}

// Initialize event listeners when the DOM is fully loaded
document.addEventListener('DOMContentLoaded', function() {
  // Close sidebar when clicking on overlay
  const overlay = document.getElementById('chatOverlay');
  if (overlay) {
    overlay.addEventListener('click', function() {
      toggleChatSidebar();
    });
  }

  // Close sidebar when pressing Escape key
  document.addEventListener('keydown', function(event) {
    const overlay = document.getElementById('chatOverlay');
    if (event.key === 'Escape' && overlay && overlay.style.visibility === 'visible') {
      toggleChatSidebar();
    }
  });

  // Handle refresh button click
  const refreshBtn = document.getElementById('refreshChatBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', function() {
      if (currentChatUsername && currentOrderNumber) {
        loadChatMessages(currentChatUsername, currentOrderNumber);
      }
    });
  }

  console.log('Chat functionality initialized');
});
