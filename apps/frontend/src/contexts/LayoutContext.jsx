import { useState, useEffect } from 'react';
import { LayoutContext } from './layout-context';

export const LayoutProvider = ({ children }) => {
  // Initialize state from localStorage if available
  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(() => {
    const saved = localStorage.getItem('layout.sidebar.open');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(false);
  const [rightSidebarContent, setRightSidebarContent] = useState(null);

  // Persist sidebar open state to localStorage
  useEffect(() => {
    localStorage.setItem('layout.sidebar.open', JSON.stringify(isLeftSidebarOpen));
  }, [isLeftSidebarOpen]);

  const toggleLeftSidebar = () => setIsLeftSidebarOpen(prev => !prev);
  const toggleRightSidebar = () => setIsRightSidebarOpen(prev => !prev);

  // Helper to open right sidebar automatically when content is set
  const setRightSidebar = (content) => {
    setRightSidebarContent(content);
    if (content && !isRightSidebarOpen) {
      setIsRightSidebarOpen(true);
    } else if (!content) {
      setIsRightSidebarOpen(false);
    }
  };

  return (
    <LayoutContext.Provider value={{
      isLeftSidebarOpen,
      toggleLeftSidebar,
      isRightSidebarOpen,
      setIsRightSidebarOpen,
      toggleRightSidebar,
      rightSidebarContent,
      setRightSidebarContent: setRightSidebar
    }}>
      {children}
    </LayoutContext.Provider>
  );
};
