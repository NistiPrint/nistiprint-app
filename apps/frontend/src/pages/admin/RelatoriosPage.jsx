import { Outlet } from 'react-router-dom';

// A barra lateral vem do registro unico em src/navigation.js.
function RelatoriosPage() {
  return (
    <div className="mx-auto w-full max-w-7xl">
      <Outlet />
    </div>
  );
}

export default RelatoriosPage;
