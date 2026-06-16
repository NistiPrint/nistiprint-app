export function getOrderTimestamps(order = {}) {
  const datas = order.datas || {};
  const snapshotLogistics = order.snapshot?.logistics || {};

  return {
    compra:
      order.data_compra_marketplace ||
      datas.compra_marketplace ||
      order.purchase_at ||
      order.dataCompraMarketplace ||
      snapshotLogistics.purchase_at ||
      snapshotLogistics.compra_marketplace ||
      null,
    pagamento:
      order.data_pagamento_marketplace ||
      datas.pagamento_marketplace ||
      order.payment_at ||
      order.dataPagamentoMarketplace ||
      snapshotLogistics.payment_at ||
      snapshotLogistics.pagamento_marketplace ||
      null,
    coleta:
      order.data_coleta ||
      datas.coleta ||
      order.collection_at ||
      order.dataColeta ||
      snapshotLogistics.collection_at ||
      snapshotLogistics.coleta ||
      null,
    envio:
      order.data_envio_marketplace ||
      datas.envio_marketplace ||
      order.marketplace_shipped_at ||
      order.dataEnvioMarketplace ||
      snapshotLogistics.marketplace_shipped_at ||
      snapshotLogistics.envio_marketplace ||
      null,
    limite:
      order.data_limite_envio ||
      datas.limite_envio ||
      order.enviar_ate_formatado ||
      snapshotLogistics.deadline ||
      snapshotLogistics.ship_by_date ||
      snapshotLogistics.expected_date ||
      null,
  };
}
