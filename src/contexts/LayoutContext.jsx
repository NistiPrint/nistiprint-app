import { createContext, useContext, useState } from 'react';

const LayoutContext = createContext();

export const useLayout = () => {
  const context = useContext(LayoutContext);
  if (!context) {
    throw new Error('useLayout must be used within a LayoutProvider');
  }
  return context;
};

export const LayoutProvider = ({ children }) => {
  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(true);
  const [leftSidebarContent, setLeftSidebarContent] = useState(null);
  const [leftSidebarMenuItems, setLeftSidebarMenuItems] = useState([]);
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(false);
  const [rightSidebarContent, setRightSidebarContent] = useState(null);

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
      setIsLeftSidebarOpen,
      toggleLeftSidebar,
      leftSidebarContent,
      setLeftSidebarContent,
      leftSidebarMenuItems,
      setLeftSidebarMenuItems,
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
