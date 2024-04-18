import axios from 'axios'
import addonData from '/src/common'
import { useState, useEffect } from 'react'
import { Panel, ScrollPanel } from '@ynput/ayon-react-components'

import PairingButton from './PairingButton'

import styled from 'styled-components'


const PairingListPanel = styled(Panel)`
  min-width: 650px;
  max-width: 650px;
  min-height: 300px;
  max-height: 90%;
`

const Warn = styled.span`
  color: red;
  font-weight: bold;
`

const Table = styled.table`
  border-collapse: collapse;
  width: 100%;

  thead {
    border-bottom: 1px solid #ccc;
  }

  th, td {
    padding: 0.5rem;
    height: 48px;
  }

  th {
    font-weight: bold;
    text-align: left;
  }
`




const PairingList = () => {
  const [pairings, setPairings] = useState([])

  const loadPairings = () => {
    axios
      .get(`${addonData.baseUrl}/pairing`)
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
      <ScrollPanel style={{flexGrow: 1}}>
        <Table>
          <thead>
            <tr>
              <th>Kitsu project name</th>
              <th>Ayon project name</th>
              <th style={{width:1}}></th>
            </tr>
          </thead>
          <tbody>
        {pairings.map((pairing) => (
          <tr>
            <td>{pairing.kitsuProjectName}</td>
            <td>{pairing.ayonProjectName || <Warn>Not paired</Warn>}</td>
            <td><PairingButton onPair={loadPairings} pairing={pairing} /></td>
          </tr>
        ))}
          </tbody>
        </Table>
      </ScrollPanel>
    </PairingListPanel>
  )
}

export default PairingList
