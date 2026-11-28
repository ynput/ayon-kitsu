import axios from 'axios'
import addonData from '/src/common'
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Section,
  Toolbar,
  Spacer,
  Panel,
  ScrollPanel,
  Button,
  Icon,
  Dialog,
} from '@ynput/ayon-react-components'

import PairingButton from './PairingButton'

import styled, { keyframes } from 'styled-components'

const ACTIVE_SYNC_STATUSES = new Set(['pending', 'restarted', 'in_progress'])
const ACTIVE_POLL_MS = 2000
const IDLE_POLL_MS = 15000

const isSyncActive = (fullSync) => {
  if (!fullSync) return false
  if (ACTIVE_SYNC_STATUSES.has(fullSync.status)) return true
  return fullSync.status === 'failed' && Boolean(fullSync.retryable)
}

const spin = keyframes`
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
`

const PageWrapper = styled(Section)`
  width: 100%;
  max-width: 820px;
  height: 85vh;
  max-height: 760px;
  min-height: 360px;
  padding: 16px;
  gap: 8px;
  box-sizing: border-box;
`

const TableContainer = styled(Panel)`
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: hidden;
`

const StatusNotice = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  min-width: 0;
  color: ${({ $tone }) => {
    if ($tone === 'error') return 'var(--md-sys-color-error)'
    if ($tone === 'warning') return 'var(--md-sys-color-warning)'
    if ($tone === 'success') return 'var(--color-hl-production)'
    return 'var(--md-sys-color-on-surface)'
  }};
`

const NoticeText = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`

const Warn = styled.span`
  color: var(--md-sys-color-error);
`

const Muted = styled.span`
  color: var(--md-sys-color-outline);
`

const NavLink = styled.a`
  color: var(--md-sys-color-primary);
  font-size: 12px;
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
`

const Table = styled.table`
  border-collapse: collapse;
  width: 100%;

  thead {
    position: sticky;
    top: 0;
    background-color: var(--md-sys-color-surface-container-low);
    border-bottom: 1px solid var(--md-sys-color-outline-variant);
    z-index: 1;
  }

  th,
  td {
    padding: 0.55rem 0.85rem;
    height: 46px;
    vertical-align: middle;
  }

  th {
    font-weight: 600;
    text-align: left;
    font-size: 12px;
    color: var(--md-sys-color-outline);
  }

  tbody tr + tr {
    border-top: 1px solid var(--md-sys-color-outline-variant);
  }
`

const ProjectCell = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
`

const StatusIndicator = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: ${({ $tone }) => {
    if ($tone === 'success') return 'var(--color-hl-production)'
    if ($tone === 'error') return 'var(--md-sys-color-error)'
    if ($tone === 'warning') return 'var(--md-sys-color-warning)'
    if ($tone === 'info') return 'var(--md-sys-color-primary)'
    return 'var(--md-sys-color-outline)'
  }};
`

const StatusButton = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  color: ${({ $tone }) => {
    if ($tone === 'error') return 'var(--md-sys-color-error)'
    if ($tone === 'warning') return 'var(--md-sys-color-warning)'
    if ($tone === 'success') return 'var(--color-hl-production)'
    return 'var(--md-sys-color-on-surface)'
  }};

  &:hover {
    text-decoration: underline;
  }
`

const ErrorDetailMeta = styled.div`
  font-size: 12px;
  color: var(--md-sys-color-outline);
  margin-bottom: 8px;
`

const ErrorDetailBox = styled.pre`
  margin: 0;
  padding: 10px 12px;
  border-radius: 4px;
  background-color: var(--md-sys-color-surface-container-lowest);
  border: 1px solid var(--md-sys-color-outline-variant);
  color: var(--md-sys-color-on-surface);
  font-family: monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 560px;
  max-height: 320px;
  overflow: auto;
`

const DialogFooterRow = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
`

const SpinningIcon = styled(Icon)`
  font-size: 16px;
  animation: ${({ $spinning }) => ($spinning ? spin : 'none')} 1.2s linear infinite;
`

const EmptyState = styled.div`
  padding: 2rem;
  text-align: center;
  color: var(--md-sys-color-outline);
  font-size: 13px;
`

const STATUS_META = {
  finished: { icon: 'check_circle', label: 'Synced', tone: 'success' },
  in_progress: { icon: 'sync', label: 'Syncing', tone: 'info', spin: true },
  pending: { icon: 'schedule', label: 'Queued', tone: 'warning' },
  restarted: { icon: 'schedule', label: 'Queued', tone: 'warning' },
  retrying: { icon: 'sync', label: 'Retrying', tone: 'warning', spin: true },
  expired: { icon: 'schedule', label: 'Expired', tone: 'warning' },
  failed: { icon: 'error', label: 'Failed', tone: 'error' },
}

const formatTimestamp = (iso) => {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

const extractErrorMessage = (error, fallback = 'Request failed') => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (error?.message) {
    return error.message
  }
  return fallback
}

const PairingList = () => {
  const [pairings, setPairings] = useState([])
  const [loadingPairings, setLoadingPairings] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [errorModal, setErrorModal] = useState(null)
  const [syncStatusData, setSyncStatusData] = useState({
    projects: {},
    processorRunning: null,
    lastServiceError: null,
  })

  const watchedSyncsRef = useRef(new Map())
  const syncStatusReqIdRef = useRef(0)
  const inFlightPollRef = useRef(false)

  const loadSyncStatus = useCallback(({ includeSettings = false } = {}) => {
    if (!addonData.baseUrl) {
      return Promise.resolve()
    }
    const reqId = ++syncStatusReqIdRef.current
    inFlightPollRef.current = true
    return axios
      .get(`${addonData.baseUrl}/sync-status`, {
        params: { include_settings: includeSettings },
      })
      .then((response) => {
        if (reqId !== syncStatusReqIdRef.current) {
          return
        }
        const data = response.data || {}
        const incomingProjects = data.projects || {}

        Object.entries(incomingProjects).forEach(([projectName, projStatus]) => {
          const fullSync = projStatus?.fullSync
          if (!fullSync) {
            return
          }
          const watched = watchedSyncsRef.current.get(projectName)
          if (!watched) {
            return
          }
          if (isSyncActive(fullSync)) {
            watched.seenActive = true
            return
          }
          const updatedChanged =
            fullSync.updatedAt && fullSync.updatedAt !== watched.initialUpdatedAt
          if (watched.seenActive || updatedChanged) {
            watchedSyncsRef.current.delete(projectName)
            if (fullSync.status === 'finished') {
              setNotice({
                tone: 'success',
                icon: 'check_circle',
                text: `Synced ${projectName}`,
              })
            } else if (fullSync.status === 'failed') {
              setNotice({
                tone: 'error',
                icon: 'error',
                text: `Sync failed for ${projectName}`,
                errorTitle: `Sync failed — ${projectName}`,
                errorMessage:
                  fullSync.error || fullSync.description || 'Sync failed.',
                updatedAt: fullSync.updatedAt,
              })
            }
          }
        })

        setSyncStatusData((prev) => {
          const mergedProjects = {}
          Object.entries(incomingProjects).forEach(([name, proj]) => {
            mergedProjects[name] = includeSettings
              ? proj
              : {
                  ...proj,
                  twoWaySyncEnabled:
                    prev.projects?.[name]?.twoWaySyncEnabled ??
                    proj.twoWaySyncEnabled,
                }
          })
          return {
            projects: mergedProjects,
            processorRunning:
              data.processorRunning !== undefined
                ? data.processorRunning
                : null,
            lastServiceError: data.lastServiceError || null,
          }
        })
      })
      .catch((err) => {
        console.error('Failed to load Kitsu sync status:', err)
      })
      .finally(() => {
        if (reqId === syncStatusReqIdRef.current) {
          inFlightPollRef.current = false
        }
      })
  }, [])

  const loadPairings = useCallback(() => {
    if (!addonData.baseUrl) {
      return
    }
    setLoadingPairings(true)
    axios
      .get(`${addonData.baseUrl}/pairing`)
      .then((response) => {
        setPairings(response.data || [])
        setLoadError(null)
      })
      .catch((err) => {
        console.error('Failed to load Kitsu pairings:', err)
        setLoadError(
          extractErrorMessage(err, 'Could not load Kitsu projects')
        )
      })
      .finally(() => {
        setLoadingPairings(false)
      })
  }, [])

  const refreshAll = useCallback(() => {
    loadPairings()
    loadSyncStatus({ includeSettings: true })
  }, [loadPairings, loadSyncStatus])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  const hasActiveSync =
    watchedSyncsRef.current.size > 0 ||
    Object.values(syncStatusData.projects || {}).some((proj) =>
      isSyncActive(proj?.fullSync)
    )

  // Chain the next poll only after the current request settles so slow
  // responses are never superseded and discarded by overlapping intervals.
  useEffect(() => {
    let cancelled = false
    let timerId = null
    const delayMs = hasActiveSync ? ACTIVE_POLL_MS : IDLE_POLL_MS

    const scheduleNext = () => {
      if (cancelled) return
      timerId = setTimeout(() => {
        if (cancelled) return
        if (inFlightPollRef.current) {
          scheduleNext()
          return
        }
        loadSyncStatus({ includeSettings: false }).finally(scheduleNext)
      }, delayMs)
    }

    scheduleNext()
    return () => {
      cancelled = true
      if (timerId !== null) {
        clearTimeout(timerId)
      }
    }
  }, [hasActiveSync, loadSyncStatus])

  const markProjectSyncQueued = useCallback(
    (projectName, syncResponse, { isPairing = false } = {}) => {
      syncStatusReqIdRef.current += 1
      inFlightPollRef.current = false
      const prevFullSync = syncStatusData.projects?.[projectName]?.fullSync
      watchedSyncsRef.current.set(projectName, {
        initialUpdatedAt: prevFullSync?.updatedAt || null,
        seenActive: false,
      })

      setSyncStatusData((prev) => ({
        ...prev,
        projects: {
          ...prev.projects,
          [projectName]: {
            ...(prev.projects?.[projectName] || { projectName }),
            fullSync: {
              eventId: syncResponse?.syncEventId || syncResponse?.eventId || '',
              topic: 'kitsu.sync',
              status: syncResponse?.status || 'pending',
              description: 'Sync queued',
              error: null,
              retryable: false,
              updatedAt: new Date().toISOString(),
            },
          },
        },
      }))

      if (syncStatusData.processorRunning === false) {
        setNotice({
          tone: 'warning',
          icon: 'warning',
          text: `Queued ${projectName} (processor offline)`,
        })
      } else {
        setNotice({
          tone: 'info',
          icon: 'schedule',
          text: isPairing
            ? `Paired ${projectName}, sync queued`
            : `Sync queued for ${projectName}`,
        })
      }

      loadSyncStatus({ includeSettings: isPairing })
    },
    [loadSyncStatus, syncStatusData.processorRunning, syncStatusData.projects]
  )

  const handleSyncTriggered = useCallback(
    (projectName, syncResponse) => {
      markProjectSyncQueued(projectName, syncResponse, { isPairing: false })
    },
    [markProjectSyncQueued]
  )

  const handlePaired = useCallback(
    (projectName, syncResponse) => {
      markProjectSyncQueued(projectName, syncResponse, { isPairing: true })
    },
    [markProjectSyncQueued]
  )

  const handleSyncError = useCallback((projectName, message) => {
    setNotice({
      tone: 'error',
      icon: 'error',
      text: `Could not sync ${projectName}`,
      errorTitle: `Sync request failed — ${projectName}`,
      errorMessage: message,
    })
  }, [])

  const renderToolbarNotice = () => {
    if (loadError) {
      return (
        <StatusButton
          type="button"
          $tone="error"
          title="View error details"
          onClick={() =>
            setErrorModal({
              title: 'Failed to load Kitsu projects',
              message: loadError,
            })
          }
        >
          <Icon icon="error" />
          <NoticeText>Failed to load Kitsu projects</NoticeText>
        </StatusButton>
      )
    }

    if (syncStatusData.processorRunning === false) {
      const err = syncStatusData.lastServiceError
      if (err) {
        const errDetail =
          err.error || err.description || 'Unknown processor error.'
        return (
          <StatusButton
            type="button"
            $tone="warning"
            title="View processor error details"
            onClick={() =>
              setErrorModal({
                title: 'Kitsu processor offline — recent error',
                message: errDetail,
                updatedAt: err.updatedAt,
              })
            }
          >
            <Icon icon="warning" />
            <NoticeText>Kitsu processor offline · View error</NoticeText>
          </StatusButton>
        )
      }
      return (
        <StatusNotice $tone="warning">
          <Icon icon="warning" />
          <NoticeText>Kitsu processor offline</NoticeText>
        </StatusNotice>
      )
    }

    if (notice) {
      if (notice.errorMessage) {
        return (
          <StatusButton
            type="button"
            $tone={notice.tone}
            title="View error details"
            onClick={() =>
              setErrorModal({
                title: notice.errorTitle || notice.text,
                message: notice.errorMessage,
                updatedAt: notice.updatedAt,
              })
            }
          >
            <Icon icon={notice.icon || 'error'} />
            <NoticeText>{notice.text}</NoticeText>
          </StatusButton>
        )
      }
      return (
        <StatusNotice $tone={notice.tone}>
          <Icon icon={notice.icon || 'info'} />
          <NoticeText>{notice.text}</NoticeText>
        </StatusNotice>
      )
    }

    if (syncStatusData.lastServiceError) {
      const errDetail =
        syncStatusData.lastServiceError.error ||
        syncStatusData.lastServiceError.description ||
        'Unknown processor error.'
      return (
        <StatusButton
          type="button"
          $tone="error"
          title="View processor error"
          onClick={() =>
            setErrorModal({
              title: 'Kitsu processor error',
              message: errDetail,
              updatedAt: syncStatusData.lastServiceError.updatedAt,
            })
          }
        >
          <Icon icon="error" />
          <NoticeText>Recent processor error</NoticeText>
        </StatusButton>
      )
    }

    return null
  }

  const renderStatusCell = (pairing, projectStatus) => {
    if (!pairing.ayonProjectName) {
      return <Muted>—</Muted>
    }

    const fullSync = projectStatus?.fullSync
    if (!fullSync) {
      return <Muted>—</Muted>
    }

    const effectiveKey =
      fullSync.status === 'failed' && fullSync.retryable
        ? 'retrying'
        : fullSync.status
    const meta = STATUS_META[effectiveKey]
    if (!meta) {
      return <Muted>—</Muted>
    }

    if (effectiveKey === 'failed') {
      const errMsg = fullSync.error || fullSync.description || 'Sync failed.'
      return (
        <StatusButton
          type="button"
          $tone="error"
          title="View error details"
          onClick={() =>
            setErrorModal({
              title: `Sync failed — ${pairing.ayonProjectName}`,
              message: errMsg,
              updatedAt: fullSync.updatedAt,
            })
          }
        >
          <Icon icon={meta.icon} style={{ fontSize: 16 }} />
          <span>{meta.label}</span>
        </StatusButton>
      )
    }

    const tooltipParts = []
    if (effectiveKey === 'retrying' && fullSync.error) {
      tooltipParts.push(`Retrying after error: ${fullSync.error}`)
    } else if (fullSync.description) {
      tooltipParts.push(fullSync.description)
    }
    if (fullSync.updatedAt) tooltipParts.push(formatTimestamp(fullSync.updatedAt))

    return (
      <StatusIndicator $tone={meta.tone} title={tooltipParts.join(' · ')}>
        <SpinningIcon $spinning={Boolean(meta.spin)} icon={meta.icon} />
        <span>{meta.label}</span>
      </StatusIndicator>
    )
  }

  return (
    <PageWrapper>
      <Toolbar>
        {renderToolbarNotice()}
        <Spacer />
        <NavLink href="/events" target="_parent" rel="noreferrer">
          Events
        </NavLink>
        <NavLink href="/services" target="_parent" rel="noreferrer">
          Services
        </NavLink>
        <Button
          icon="refresh"
          tooltip="Refresh"
          disabled={loadingPairings}
          onClick={refreshAll}
        />
      </Toolbar>

      <TableContainer>
        <ScrollPanel style={{ height: '100%' }}>
          {loadingPairings && pairings.length === 0 ? (
            <EmptyState>Loading Kitsu projects...</EmptyState>
          ) : pairings.length === 0 ? (
            <EmptyState>
              {loadError ? loadError : 'No Kitsu projects found.'}
            </EmptyState>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Kitsu project</th>
                  <th>AYON project</th>
                  <th>Status</th>
                  <th style={{ width: 1 }}></th>
                </tr>
              </thead>
              <tbody>
                {pairings.map((pairing) => {
                  const projectStatus = pairing.ayonProjectName
                    ? syncStatusData.projects?.[pairing.ayonProjectName]
                    : null
                  return (
                    <tr key={pairing.kitsuProjectId}>
                      <td>{pairing.kitsuProjectName}</td>
                      <td>
                        {pairing.ayonProjectName ? (
                          <ProjectCell>
                            <span>{pairing.ayonProjectName}</span>
                            {projectStatus?.twoWaySyncEnabled && (
                              <Icon
                                icon="sync_alt"
                                title="Two-way sync enabled"
                                style={{
                                  fontSize: 15,
                                  color: 'var(--md-sys-color-primary)',
                                }}
                              />
                            )}
                          </ProjectCell>
                        ) : (
                          <Warn>Not paired</Warn>
                        )}
                      </td>
                      <td>{renderStatusCell(pairing, projectStatus)}</td>
                      <td>
                        <PairingButton
                          onPair={loadPairings}
                          onPaired={handlePaired}
                          onSyncTriggered={handleSyncTriggered}
                          onSyncError={handleSyncError}
                          pairing={pairing}
                          syncState={projectStatus}
                        />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          )}
        </ScrollPanel>
      </TableContainer>

      {errorModal && (
        <Dialog
          visible={true}
          onHide={() => setErrorModal(null)}
          header={errorModal.title}
        >
          {errorModal.updatedAt && (
            <ErrorDetailMeta>
              {formatTimestamp(errorModal.updatedAt)}
            </ErrorDetailMeta>
          )}
          <ErrorDetailBox>{errorModal.message}</ErrorDetailBox>
          <DialogFooterRow>
            <NavLink href="/events" target="_parent" rel="noreferrer">
              Open Events
            </NavLink>
            <Spacer />
            <Button label="Close" onClick={() => setErrorModal(null)} />
          </DialogFooterRow>
        </Dialog>
      )}
    </PageWrapper>
  )
}

export default PairingList
