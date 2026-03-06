/**
 * Utilitários para limpeza manual de sessões e cache
 */

export const clearAllSessions = () => {
  // Clear localStorage
  localStorage.clear();

  // Clear sessionStorage
  sessionStorage.clear();

  // Clear cookies related to the app
  document.cookie.split(";").forEach((c) => {
    document.cookie = c
      .replace(/^ +/, "")
      .replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
  });

  // Force reload to clear any cached state
  window.location.href = '/login';
};

export const forceLogout = () => {
  // Clear client-side data
  clearAllSessions();

  // Try to call logout API if possible
  fetch('/api/v2/logout', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  }).catch(() => {
    // Ignore errors - we're clearing anyway
  });
};

export const clearBrowserCache = () => {
  // Clear all caches
  if ('caches' in window) {
    caches.keys().then((names) => {
      names.forEach((name) => {
        caches.delete(name);
      });
    });
  }

  // Force reload
  window.location.reload(true);
};
