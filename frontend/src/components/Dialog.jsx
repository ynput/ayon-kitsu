import styled from 'styled-components'
import { Panel } from '@ynput/ayon-react-components'

const Shade = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
`

const DialogWindow = styled(Panel)`
  min-width: 400px;
  min-height: 200px;
`


const Dialog = ({ visible, onHide, children }) => {

  if (!visible) {
    return null
  }

  const handleClose = (event) => {
    if (event.currentTarget !== event.target) return
    event.preventDefault()
    onHide()
  }

  return (
    <Shade onClick={handleClose}>
      <DialogWindow>
        {children}
      </DialogWindow>
    </Shade>
  )
}

export default Dialog
