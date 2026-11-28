import axios from 'axios'
import addonData from '/src/common'

import { useState, useEffect } from 'react'

import {
  FormLayout,
  FormRow,
  Button,
  InputText,
  Dialog,
} from '@ynput/ayon-react-components'
import styled from 'styled-components'

const ErrorText = styled.div`
  color: var(--md-sys-color-error);
  margin-top: 0.75rem;
  font-size: 13px;
  max-width: 400px;
`

const DialogActions = styled.div`
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
`

const ActionButton = styled(Button)`
  min-width: 116px;
`

const extractErrorMessage = (error, fallback = 'Request failed') => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ')
  }
  if (error?.message) {
    return error.message
  }
  return fallback
}

const PairingDialog = ({ pairing, onHide, onPaired }) => {
  const [ayonProjectName, setAyonProjectName] = useState('')
  const [ayonProjectCode, setAyonProjectCode] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let name = pairing.kitsuProjectName || ''
    name = name.replace(/[^a-zA-Z0-9_]/g, '_')
    name = name.replace(/_+/g, '_')
    name = name.replace(/^_/, '')
    name = name.replace(/_$/, '')
    setAyonProjectName(name)

    let code = pairing.kitsuProjectCode || pairing.kitsuProjectName || ''
    code = code.replace(/[^a-zA-Z0-9]/g, '')
    code = code.replace(/_+/g, '')
    code = code.replace(/^_/, '')
    code = code.replace(/_$/, '')
    code = code.toLowerCase()
    code = code.substring(0, 6)
    setAyonProjectCode(code)
  }, [pairing])

  const onPair = () => {
    setLoading(true)
    setError(null)
    axios
      .post(`${addonData.baseUrl}/pairing`, {
        kitsuProjectId: pairing.kitsuProjectId,
        ayonProjectName,
        ayonProjectCode,
      })
      .then((response) => {
        setError(null)
        if (onPaired) {
          onPaired(ayonProjectName, response.data)
        }
        onHide()
      })
      .catch((err) => {
        console.error('Failed to pair Kitsu project:', err)
        setError(extractErrorMessage(err, 'Unable to pair project'))
      })
      .finally(() => {
        setLoading(false)
      })
  }

  // Render submit actions inside the body instead of Dialog's `footer` prop:
  // @ynput/ayon-react-components@0.4.18 memoizes `footer` solely on `header`,
  // which would otherwise capture a stale `onPair` closure with empty values.
  return (
    <Dialog
      visible={true}
      onHide={onHide}
      header={`Pair ${pairing.kitsuProjectName}`}
    >
      <FormLayout>
        <FormRow label="AYON project name">
          <InputText
            value={ayonProjectName}
            disabled={loading}
            onChange={(e) => setAyonProjectName(e.target.value)}
          />
        </FormRow>
        <FormRow label="AYON project code">
          <InputText
            value={ayonProjectCode}
            disabled={loading}
            onChange={(e) => setAyonProjectCode(e.target.value)}
          />
        </FormRow>
      </FormLayout>
      {error && <ErrorText>{error}</ErrorText>}
      <DialogActions>
        <Button label="Cancel" disabled={loading} onClick={onHide} />
        <Button
          variant="filled"
          label={loading ? 'Pairing...' : 'Pair'}
          disabled={loading}
          onClick={onPair}
        />
      </DialogActions>
    </Dialog>
  )
}

const PairingButton = ({
  onPair,
  onPaired,
  onSyncTriggered,
  onSyncError,
  pairing,
  syncState,
}) => {
  const [showPairingDialog, setShowPairingDialog] = useState(false)
  const [loading, setLoading] = useState(false)

  const fullSync = syncState?.fullSync
  const syncStatus = fullSync?.status
  const isQueued = syncStatus === 'pending' || syncStatus === 'restarted'
  const isInProgress = syncStatus === 'in_progress'
  const isRetrying = syncStatus === 'failed' && Boolean(fullSync?.retryable)
  const isBusy = loading || isQueued || isInProgress || isRetrying

  const onSync = () => {
    if (isBusy) {
      return
    }
    setLoading(true)
    axios
      .post(`${addonData.baseUrl}/sync/${pairing.ayonProjectName}`)
      .then((response) => {
        if (onSyncTriggered) {
          onSyncTriggered(pairing.ayonProjectName, response.data)
        }
        if (onPair) {
          onPair()
        }
      })
      .catch((err) => {
        console.error('Failed to trigger Kitsu sync:', err)
        if (onSyncError) {
          onSyncError(
            pairing.ayonProjectName,
            extractErrorMessage(err, 'Failed to queue sync')
          )
        }
      })
      .finally(() => {
        setLoading(false)
      })
  }

  if (!pairing.ayonProjectName) {
    return (
      <>
        {showPairingDialog && (
          <PairingDialog
            pairing={pairing}
            onPaired={onPaired}
            onHide={() => {
              setShowPairingDialog(false)
              if (onPair) {
                onPair()
              }
            }}
          />
        )}
        <ActionButton
          label="Pair project"
          icon="link"
          onClick={() => setShowPairingDialog(true)}
        />
      </>
    )
  }

  let label = 'Sync now'
  if (loading || isQueued) {
    label = 'Queued'
  } else if (isInProgress) {
    label = 'Syncing'
  } else if (isRetrying) {
    label = 'Retrying'
  }

  return (
    <ActionButton
      label={label}
      icon="sync"
      disabled={isBusy}
      onClick={onSync}
    />
  )
}

export default PairingButton
