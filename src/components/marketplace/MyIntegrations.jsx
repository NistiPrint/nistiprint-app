import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import LiveOrderConsultation from './LiveOrderConsultation'
import './Marketplace.css'

const MyIntegrations = () => {
  const [installations, setInstallations] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    fetchInstallations()
  }, [])

  const fetchInstallations = async () => {
    try {
      // In a real app, user_id would come from authentication
      const response = await fetch(
        '/api/v2/marketplace/installed?user_id=default_user'
      )
      const data = await response.json()
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
                  {installation.sync_status === 'success' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-success'></span> OK
                    </React.Fragment>
                  ) : installation.sync_status === 'error' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-error'></span> Erro
                    </React.Fragment>
                  ) : installation.sync_status === 'syncing' ? (
                    <React.Fragment>
                      <span className='sync-indicator sync-syncing'></span> Sync
                    </React.Fragment>
                  ) : (
                    <React.Fragment>
                      <span className='sync-indicator sync-pending'></span>{' '}
                      Pendente
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
