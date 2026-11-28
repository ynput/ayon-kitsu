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
const NOTICE_TTL_MS = 8000

const isSyncActive = (fullSync) => {
  if (!fullSync) return false
  if (ACTIVE_SYNC_STATUSES.has(fullSync.status)) return true
  return fullSync.status === 'failed' && Boolean(fullSync.retryable)
}

const parseTimeMs = (iso) => {
  if (!iso) return 0
  const ms = Date.parse(iso)
  return Number.isFinite(ms) ? ms : 0
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

const StatusCellRow = styled.div`
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
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

  // Auto-expire transient action notices so they never hide newer processor errors.
  useEffect(() => {
    if (!notice || notice.tone === 'error' || notice.tone === 'warning') {
      return undefined
    }
    const timerId = setTimeout(() => {
      setNotice((current) =>
        current && current.createdAt === notice.createdAt ? null : current
      )
    }, NOTICE_TTL_MS)
    return () => clearTimeout(timerId)
  }, [notice])

  const loadSyncStatus = useCallback(() => {
    if (!addonData.baseUrl) {
      return Promise.resolve()
    }
    const reqId = ++syncStatusReqIdRef.current
    inFlightPollRef.current = true
    return axios
      .get(`${addonData.baseUrl}/sync-status`)
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
                createdAt: Date.now(),
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
                createdAt: Date.now(),
              })
            }
          }
        })

        setSyncStatusData({
          projects: incomingProjects,
          processorRunning:
            data.processorRunning !== undefined ? data.processorRunning : null,
          lastServiceError: data.lastServiceError || null,
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
    loadSyncStatus()
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
        loadSyncStatus().finally(scheduleNext)
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
          createdAt: Date.now(),
        })
      } else {
        setNotice({
          tone: 'info',
          icon: 'schedule',
          text: isPairing
            ? `Paired ${projectName}, sync queued`
            : `Sync queued for ${projectName}`,
          createdAt: Date.now(),
        })
      }

      loadSyncStatus()
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
      createdAt: Date.now(),
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

    const serviceErr = syncStatusData.lastServiceError

    if (syncStatusData.processorRunning === false) {
      if (serviceErr) {
        const errDetail =
          serviceErr.error ||
          serviceErr.description ||
          'Unknown processor error.'
        return (
          <StatusButton
            type="button"
            $tone="warning"
            title="View processor error details"
            onClick={() =>
              setErrorModal({
                title: 'Kitsu processor offline — recent error',
                message: errDetail,
                updatedAt: serviceErr.updatedAt,
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

    // If a newer processor error arrived after the last action notice,
    // surface the processor error instead of letting an old notice mask it.
    const serviceErrIsNewer =
      serviceErr &&
      (!notice || parseTimeMs(serviceErr.updatedAt) > (notice.createdAt || 0))

    if (serviceErrIsNewer) {
      const errDetail =
        serviceErr.error ||
        serviceErr.description ||
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
              updatedAt: serviceErr.updatedAt,
            })
          }
        >
          <Icon icon="error" />
          <NoticeText>Recent processor error</NoticeText>
        </StatusButton>
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

    return null
  }

  const renderStatusCell = (pairing, projectStatus) => {
    if (!pairing.ayonProjectName) {
      return <Muted>—</Muted>
    }

    const fullSync = projectStatus?.fullSync
    const inboundErr = projectStatus?.lastInboundError
    const showInboundErr = Boolean(
      inboundErr &&
        (!fullSync ||
          fullSync.status !== 'finished' ||
          parseTimeMs(inboundErr.updatedAt) > parseTimeMs(fullSync.updatedAt))
    )

    if (!fullSync && !showInboundErr) {
      return <Muted>—</Muted>
    }

    let fullSyncEl = null
    if (fullSync) {
      const effectiveKey =
        fullSync.status === 'failed' && fullSync.retryable
          ? 'retrying'
          : fullSync.status
      const meta = STATUS_META[effectiveKey]
      if (meta) {
        if (effectiveKey === 'failed') {
          const errMsg =
            fullSync.error || fullSync.description || 'Sync failed.'
          fullSyncEl = (
            <StatusButton
              type="button"
              $tone="error"
              title="View full-sync error details"
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
        } else {
          const tooltipParts = []
          if (effectiveKey === 'retrying' && fullSync.error) {
            tooltipParts.push(`Retrying after error: ${fullSync.error}`)
          } else if (fullSync.description) {
            tooltipParts.push(fullSync.description)
          }
          if (fullSync.updatedAt) {
            tooltipParts.push(formatTimestamp(fullSync.updatedAt))
          }
          fullSyncEl = (
            <StatusIndicator $tone={meta.tone} title={tooltipParts.join(' · ')}>
              <SpinningIcon $spinning={Boolean(meta.spin)} icon={meta.icon} />
              <span>{meta.label}</span>
            </StatusIndicator>
          )
        }
      }
    }

    let inboundEl = null
    if (showInboundErr) {
      const inboundMsg =
        inboundErr.error || inboundErr.description || 'Inbound update failed.'
      inboundEl = (
        <StatusButton
          type="button"
          $tone="error"
          title="View inbound live-sync error"
          onClick={() =>
            setErrorModal({
              title: `Inbound sync failed — ${pairing.ayonProjectName}`,
              message: inboundMsg,
              updatedAt: inboundErr.updatedAt,
            })
          }
        >
          <Icon icon="error" style={{ fontSize: 15 }} />
          <span>Live error</span>
        </StatusButton>
      )
    }

    return (
      <StatusCellRow>
        {fullSyncEl}
        {inboundEl}
      </StatusCellRow>
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
                        {pairing.ayonProjectName || <Warn>Not paired</Warn>}
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
