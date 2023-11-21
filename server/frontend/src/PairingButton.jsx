import axios from 'axios'
import addonData from '/src/common'

import { useState, useEffect } from 'react'

import { FormLayout, FormRow, Button, InputText } from '@ynput/ayon-react-components'
import Dialog from '/src/components/Dialog'
import styled from 'styled-components'


const ErrorContainer = styled.div`
  color: red;
  font-weight: bold;
  margin-top: 1rem;
  max-width: 400px;

`

const ActionButton = styled(Button)`
  width: 120px;
`


const PairingDialog = ({ pairing, onHide }) => {
  const [ayonProjectName, setAyonProjectName] = useState()
  const [ayonProjectCode, setAyonProjectCode] = useState()
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  //create a default name
  useEffect(() => {
    // create a ayon name and ayon code
    // based on pairing.kitsuProjectName
    // ayon project names can only contain alphanumeric characters and underscores
    // ayon project codes can only contain alphanumeric characters and must be 3-6 characters long

    let name = pairing.kitsuProjectName
    name = name.replace(/[^a-zA-Z0-9_]/g, '_')
    name = name.replace(/_+/g, '_')
    name = name.replace(/^_/, '')
    name = name.replace(/_$/, '')
    setAyonProjectName(name)

    let code = pairing.kitsuProjectCode || pairing.kitsuProjectName
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
    axios
      .post(
        `${addonData.baseUrl}/pairing`, {
        kitsuProjectId: pairing.kitsuProjectId,
        ayonProjectName: ayonProjectName,
        ayonProjectCode: ayonProjectCode,
      })
      .then((response) => {
        setError(null)
        onHide()
      })
      .catch((error) => {
        console.log(error)
        setError(error.response.data?.detail || "error")
      })
      .finally(() => {
        setLoading(false)
      })
  }

  return (
    <Dialog visible={true} onHide={onHide}>
      <h1>Pair Kitsu project {pairing.kitsuProjectName}</h1>

      <FormLayout>
        <FormRow label="Ayon project name">
          <InputText
            value={ayonProjectName}
            onChange={(e) => setAyonProjectName(e.target.value)}
          />
        </FormRow>
        <FormRow label="Ayon project code">
          <InputText
            value={ayonProjectCode}
            onChange={(e) => setAyonProjectCode(e.target.value)}
          />
        </FormRow>
        <FormRow>
          <Button label="Pair" onClick={onPair} />
        </FormRow>
      </FormLayout>
      {error && (
        <ErrorContainer>
          {error}
        </ErrorContainer>
      )}
      {loading && "Please wait..."}
    </Dialog>
  )
}


const PairingButton = ({ onPair, pairing }) => {
  const [showPairingDialog, setShowPairingDialog] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const onSync = () => {
    axios
      .post(`${addonData.baseUrl}/sync/${pairing.ayonProjectName}`)
      .then((response) => {
        setError(null)
        onHide()
      })
      .catch((error) => {
        console.log(error)
        setError(error.response.data?.detail || "error")
      })
      .finally(() => {
        setLoading(false)
      })
  }

  // project is not paired yet show pairing button
  if (!pairing.ayonProjectName) {
    return (
      <>
        {showPairingDialog && (
          <PairingDialog
            pairing={pairing}
            onHide={() => {
              setShowPairingDialog(false)
              onPair()
            }}
          />
        )}
        <ActionButton
          label={`Pair project`}
          icon="link"
          onClick={() => {
            setShowPairingDialog(true)
          }}
        />
      </>
    )
  }


  return (
    <ActionButton
      label={`Sync now`}
      icon="sync"
      onClick={onSync}
    />
  )

}


export default PairingButton
