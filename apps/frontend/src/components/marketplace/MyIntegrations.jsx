import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import MarketplaceService from '@/services/MarketplaceService'
import LiveOrderConsultation from './LiveOrderConsultation'
import './Marketplace.css'

const getAccountIdentifier = installation => {
  const credentialStatus = installation?.credential_status || {}
  const config = installation?.config || {}
  const credentials = installation?.credentials || {}
  return (
    credentialStatus.account_identifier ||
    config.account_identifiers?.primary ||
    config.shop_id ||
    config.seller_id ||
    config.user_id ||
    config.account_id ||
    credentials.account_identifiers?.primary ||
    credentials.shop_id ||
    credentials.seller_id ||
    credentials.user_id ||
    credentials.account_id ||
    ''
  )
}

const getTokenStatusLabel = installation => {
  const status = installation?.credential_status?.token_status || 'unknown'
  const labels = {
    valid: 'Valida',
    expiring_soon: 'Expirando',
    expired: 'Expirada',
    missing: 'Ausente',
    refresh_failed: 'Falha ao renovar',
    refresh_warning: 'Atencao',
    external_sync_stale: 'Sync externo atrasado',
    external_sync_warning: 'Sync externo com alerta',
    reauth_required: 'Reautorizacao',
    not_required: 'Nao requerida',
  }
  return labels[status] || 'Desconhecida'
}

const isMarketplaceAccountModule = moduleId =>
  moduleId && moduleId !== 'bling'

const MyIntegrations = () => {
  const [installations, setInstallations] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [renewingId, setRenewingId] = useState(null)
  const [syncingAccountIdentityId, setSyncingAccountIdentityId] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    fetchInstallations()
  }, [])

  const fetchInstallations = async () => {
    try {
      const data = await MarketplaceService.getInstalledIntegrations()
      if (!data.success) {
        throw new Error(data.error || 'Erro ao carregar integra??es')
      }
      setInstallations(data.installations || [])
    } catch (error) {
      console.error('Error fetching installations:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const syncIntegration = async instanceId => {
    try {
      const response = await fetch(
        `/api/v2/marketplace/installed/${instanceId}/sync`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        }
      )

      const data = await response.json()

      if (data.success) {
        // Update the sync status in the UI
        setInstallations(prev =>
          prev.map(installation =>
            installation.id === instanceId
              ? {
                  ...installation,
                  sync_status: 'syncing',
                  last_sync: new Date().toISOString(),
                }
              : installation
          )
        )
        alert('Sincronização iniciada com sucesso!')
      } else {
        throw new Error(data.error || 'Erro desconhecido')
      }
    } catch (error) {
      console.error('Sync error:', error)
      alert(`Erro ao iniciar sincronização: ${error.message}`)
    }
  }

  const uninstallIntegration = async instanceId => {
    if (
      !window.confirm(
        'Tem certeza que deseja desinstalar esta integração? Esta ação não pode ser desfeita.'
      )
    ) {
      return
    }

    try {
      const response = await fetch(
        `/api/v2/marketplace/installed/${instanceId}`,
        {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
          },
        }
      )

      const data = await response.json()

      if (data.success) {
        // Remove the installation from the UI
        setInstallations(prev =>
          prev.filter(installation => installation.id !== instanceId)
        )
        alert('Integração desinstalada com sucesso!')
      } else {
        throw new Error(data.error || 'Erro desconhecido')
      }
    } catch (error) {
      console.error('Uninstall error:', error)
      alert(`Erro ao desinstalar: ${error.message}`)
    }
  }

  const renewToken = async instanceId => {
    if (!window.confirm('Deseja renovar o token desta integração?')) {
      return
    }

    setRenewingId(instanceId)
    try {
      const response = await fetch(
        `/api/v2/marketplace/installed/${instanceId}/renew`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        }
      )

      const data = await response.json()

      if (data.status === 'success') {
        setInstallations(prev =>
          prev.map(installation =>
            installation.id === instanceId
              ? data.installation || installation
              : installation
          )
        )
        alert('Token renovado com sucesso!')
      } else {
        throw new Error(data.error || 'Erro ao renovar token')
      }
    } catch (error) {
      console.error('Renew token error:', error)
      alert(`Erro ao renovar token: ${error.message}`)
      
      // Update UI to show error
      setInstallations(prev =>
        prev.map(installation =>
          installation.id === instanceId
            ? {
                ...installation,
                credential_status: {
                  ...(installation.credential_status || {}),
                  token_status: 'refresh_failed',
                  refresh_error: error.message,
                },
              }
            : installation
        )
      )
    } finally {
      setRenewingId(null)
    }
  }

  const syncAccountIdentity = async instanceId => {
    setSyncingAccountIdentityId(instanceId)
    try {
      const data = await MarketplaceService.syncAccountIdentity(instanceId)
      if (!data.success) {
        throw new Error(data.error || 'Erro ao sincronizar identificador da conta')
      }

      setInstallations(prev =>
        prev.map(installation =>
          installation.id === instanceId
            ? data.installation || installation
            : installation
        )
      )
      alert(
        `Identificador sincronizado com sucesso: ${data.account_identifier_kind}=${data.account_identifier}`
      )
    } catch (error) {
      console.error('Sync account identity error:', error)
      alert(`Erro ao sincronizar identificador da conta: ${error.message}`)
    } finally {
      setSyncingAccountIdentityId(null)
    }
  }

  if (isLoading) {
    return <div>Carregando...</div>
  }

  return (
    <div className='container'>
      <div className='my-integrations-header'>
        <h1>🔌 Minhas Integrações</h1>
        <p>Gerencie suas integrações instaladas e monitore seu status</p>
      </div>

      <div style={{ marginBottom: '30px', textAlign: 'right' }}>
        <button
          className='btn btn-primary'
          style={{ fontSize: '16px', padding: '12px 24px' }}
          onClick={() => navigate('/marketplace')}>
          ➕ Nova Integração
        </button>
      </div>

      {installations.length > 0 ? (
        <div className='integrations-grid'>
          {installations.map(installation => (
            <div
              key={installation.id}
              className={`integration-card ${
                installation.sync_status === 'error' ? 'error' : ''
              } ${installation.sync_status === 'warning' ? 'warning' : ''}`}>
              <div className='integration-icon'>
                {installation.module_icon ? (
                  <img
                    src={installation.module_icon}
                    alt={`${installation.module_name} Icon`}
                    onError={e => {
                      e.target.style.display = 'none'
                    }}
                  />
                ) : (
                  <span>🔌</span>
                )}
              </div>

              <div className='integration-name'>
                {installation.instance_name}
              </div>

              <div className='integration-module'>
                {installation.module_name}
              </div>

              {getAccountIdentifier(installation) && (
                <div className='integration-module'>
                  Webhook: {getAccountIdentifier(installation)}
                </div>
              )}

              <div className='integration-description'>
                {installation.module_description}
              </div>

              <div className='integration-status'>
                <span
                  className={`status-badge ${
                    installation.is_active ? 'status-active' : 'status-inactive'
                  }`}>
                  {installation.is_active ? 'Ativo' : 'Inativo'}
                </span>

                <span>
                  {installation.credential_status?.token_status === 'valid' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-success'></span> OK
                    </React.Fragment>
                  ) : installation.credential_status?.token_status === 'expiring_soon' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-pending'></span> Expirando
                    </React.Fragment>
                  ) : installation.credential_status?.token_status === 'expired' || installation.credential_status?.token_status === 'refresh_failed' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-error'></span> Erro
                      {installation.credential_status?.refresh_error && (
                        <span className="text-xs text-red-500 ml-2">
                          {installation.credential_status.refresh_error}
                        </span>
                      )}
                    </React.Fragment>
                  ) : installation.sync_status === 'syncing' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-syncing'></span> Sync
                    </React.Fragment>
                  ) : (
                    <React.Fragment>
                      <span className='sync-indicator sync-pending'></span>{' '}
                      {getTokenStatusLabel(installation)}
                    </React.Fragment>
                  )}
                </span>
              </div>

              <div className='integration-actions'>
                <LiveOrderConsultation
                  integrationId={installation.id}
                  moduleName={installation.module_name}
                  moduleId={installation.module_id}
                />
                <button
                  className='btn btn-sm btn-info'
                  onClick={() => syncIntegration(installation.id)}>
                  Sincronizar
                </button>
                {isMarketplaceAccountModule(installation.module_id) && (
                  <button
                    className='btn btn-sm btn-info'
                    onClick={() => syncAccountIdentity(installation.id)}
                    disabled={syncingAccountIdentityId === installation.id}>
                    {syncingAccountIdentityId === installation.id ? (
                      <><RefreshCw className="h-4 w-4 mr-1 animate-spin" /> Conta...</>
                    ) : (
                      <>Sync conta</>
                    )}
                  </button>
                )}
                {/* Botão Renovar Token - Apenas para Shopee */}
                {installation.credential_status?.actions?.can_refresh && (
                  <button
                    className='btn btn-sm btn-warning'
                    onClick={() => renewToken(installation.id)}
                    disabled={renewingId === installation.id}>
                    {renewingId === installation.id ? (
                      <><RefreshCw className="h-4 w-4 mr-1 animate-spin" /> Renovando...</>
                    ) : (
                      <><RefreshCw className="h-4 w-4 mr-1" /> Renovar Token</>
                    )}
                  </button>
                )}
                <button
                  className='btn btn-sm btn-warning'
                  onClick={() =>
                    alert(
                      'Funcionalidade de edição não implementada no exemplo'
                    )
                  }>
                  Editar
                </button>
                <button
                  className='btn btn-sm btn-danger'
                  onClick={() => uninstallIntegration(installation.id)}>
                  Desinstalar
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className='no-integrations'>
          <h3>Nenhuma integração instalada</h3>
          <p>
            Você ainda não instalou nenhuma integração. Explore o marketplace
            para encontrar integrações úteis.
          </p>
          <button
            className='btn btn-primary'
            style={{ marginTop: '15px' }}
            onClick={() => navigate('/marketplace')}>
            Explorar Marketplace
          </button>
        </div>
      )}
    </div>
  )
}

export default MyIntegrations
