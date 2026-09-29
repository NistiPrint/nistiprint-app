import { Outlet } from 'react-router-dom';

// A barra lateral vem do registro unico em src/navigation.js.
function VendasPage() {
  return (
    <div className="h-full">
      <Outlet />
    </div>
  );
}

export default VendasPage;
