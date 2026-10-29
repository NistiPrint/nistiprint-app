export default function ColetaRegistroDetalhes({ coleta }) {
  const itens = Array.isArray(coleta.itens_snapshot) ? coleta.itens_snapshot : null
  const totalFinalizado = itens?.reduce((sum, item) => sum + Number(item.quantidade_finalizada || 0), 0)

  return (
    <div className="space-y-1 text-sm">
      <div className="font-medium">
        {coleta.quantidade} un. coletadas
        {coleta.saldo_restante_apos != null && (
          <span className="ml-2 text-amber-700">· {coleta.saldo_restante_apos} un. pendentes de coleta</span>
        )}
      </div>
      {itens ? (
        <details className="text-xs text-gray-600">
          <summary className="cursor-pointer">{totalFinalizado} un. finalizadas na produção · ver SKUs</summary>
          <p className="mt-2 text-gray-500">Este retrato não identifica quais SKUs foram coletados.</p>
          <div className="mt-2 max-h-56 overflow-auto rounded border bg-white">
            <table className="w-full text-left">
              <thead className="sticky top-0 bg-gray-50">
                <tr>
                  <th className="p-2">Item / SKU</th>
                  <th className="p-2 text-right">Previsto</th>
                  <th className="p-2 text-right">Finalizado</th>
                  <th className="p-2 text-right">Falta finalizar</th>
                </tr>
              </thead>
              <tbody>
                {itens.map((item) => (
                  <tr key={item.item_demanda_id} className="border-t">
                    <td className="p-2">
                      <div className="font-medium">{item.sku || `Item #${item.item_demanda_id}`}</div>
                      {item.descricao && <div className="text-gray-500">{item.descricao}</div>}
                    </td>
                    <td className="p-2 text-right">{item.quantidade_prevista}</td>
                    <td className="p-2 text-right">{item.quantidade_finalizada}</td>
                    <td className="p-2 text-right">{item.quantidade_pendente_finalizacao}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : (
        <span className="text-xs text-gray-500">Retrato de produção indisponível para este registro antigo.</span>
      )}
    </div>
  )
}
