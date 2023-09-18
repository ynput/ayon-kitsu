import axios from 'axios'
import {BASE_URL} from '/src/common'
import { useState, useEffect } from 'react'
import { Panel, ScrollPanel, FormLayout, FormRow } from '@ynput/ayon-react-components'

import PairingButton from './PairingButton'

import styled from 'styled-components'


const PairingListPanel = styled(Panel)`
  min-width: 650px;
  max-width: 650px;
  min-height: 300px;
  max-height: 90%;
`



const PairingList = () => {
  const [pairings, setPairings] = useState([])

  const loadPairings = () => {
    axios
      .get(`${BASE_URL}/pairing`)
      .then((response) => {
        setPairings(response.data)
      })
      .catch((error) => {
        //console.log(error)
      })
  }

  useEffect(() => {
    loadPairings()
  }, [])


  return (
    <PairingListPanel>
      <h1>Kitsu project pairings</h1>
      <ScrollPanel style={{flexGrow: 1}}>
        <FormLayout style={{width: '90%'}}>
        {pairings.map((pairing) => (
          <FormRow label={pairing.kitsuProjectName} key={pairing.kitsuProjectId}>
            {pairing.ayonProjectName || <PairingButton onPair={loadPairings} pairing={pairing} />}
          </FormRow>
        ))}
        </FormLayout>
      </ScrollPanel>
    </PairingListPanel>
  )
}

export default PairingList
