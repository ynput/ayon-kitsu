import axios from 'axios'
import React, { useContext, useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { AddonProvider, AddonContext } from '@ynput/ayon-react-addon-provider'

import PairingList from './PairingList'

import '@ynput/ayon-react-components/dist/style.css'

import styled from 'styled-components'


const MainContainer = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;

  h1 {
    font-size: 18px;
    padding: 0 0 10px 0;
    border-bottom: 1px solid #ccc;
  }
`



const App = () => {
  const accessToken = useContext(AddonContext).accessToken
  const [tokenSet, setTokenSet] = useState(false)

  useEffect(() => {
    if (accessToken && !tokenSet) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${accessToken}`
      setTokenSet(true)
    }
  }, [accessToken, tokenSet])

  if (!tokenSet) {
    return "no token"
  }

  return <PairingList />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AddonProvider debug>
      <MainContainer>
        <App />
      </MainContainer>
    </AddonProvider>
  </React.StrictMode>,
)
