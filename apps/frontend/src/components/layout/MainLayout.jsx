import { LayoutProvider } from '@/contexts/LayoutContext';
import { Outlet } from 'react-router-dom';
import Header from './Header';
import RightSidebar from './RightSidebar';
import Sidebar from './Sidebar';

function MainLayout() {
  return (
    <LayoutProvider>
      <div className="flex flex-col h-screen bg-gray-50/50 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden relative">
          <Sidebar />
          <main className="flex-1 overflow-y-auto px-4 py-4 md:px-6 md:py-6 bg-background/50">
            <Outlet />
          </main>
          <RightSidebar />
        </div>
      </div>
    </LayoutProvider>
  );
}

export default MainLayout;
