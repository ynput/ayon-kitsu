import axios from 'axios'
import {BASE_URL} from '/src/common'

import { useState, useEffect } from 'react'

import { FormLayout, FormRow, Button, InputText } from '@ynput/ayon-react-components'
import Dialog from '/src/components/Dialog'

const PairingDialog = ({pairing, onHide}) => {
  const [ayonProjectName, setAyonProjectName] = useState()
  const [ayonProjectCode, setAyonProjectCode] = useState()

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

    let code = name
    code = code.replace(/[^a-zA-Z0-9]/g, '')
    code = code.replace(/_+/g, '')
    code = code.replace(/^_/, '')
    code = code.replace(/_$/, '')
    code = code.toLowerCase()
    code = code.substring(0, 6)
    setAyonProjectCode(code)

  }, [pairing])


  const onPair = () => {

    axios
      .get(`${BASE_URL}/pairing`)
      .then((response) => {
        setPairings(response.data)
      })
      .catch((error) => {
        //console.log(error)
      })

  }

  return (
    <Dialog visible={true} onHide={onHide}>
      <h1>Pair Kitsu project {pairing.kitsuProjectName}</h1>

      <FormLayout>
        <FormRow label="Ayon project name">
          <InputText 
            value={ayonProjectName} 
            onChange={setAyonProjectName} 
          />
        </FormRow>
        <FormRow label="Ayon project code">
          <InputText 
            value={ayonProjectCode} 
            onChange={setAyonProjectCode} 
          />
        </FormRow>
        <FormRow>
          <Button label="Pair" onClick={onPair} />
        </FormRow>
      </FormLayout>
    </Dialog>
  )
}


const PairingButton = ({onPair, pairing}) => {
  const [loading, setLoading] = useState(false)
  const [showPairingDialog, setShowPairingDialog] = useState(false)

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
      <Button 
        label={`Pair ${pairing.kitsuProjectName}`} 
        onClick={() => {
          setShowPairingDialog(true)
        }} 
      />
    </>
  )

}


export default PairingButton
