const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  notify(payload) {
    ipcRenderer.send('desktop-notify', payload)
  },
  apiBase: process.env.SUPERCOURSE_API_BASE || '',
  showMain() {
    ipcRenderer.send('desktop-show-main')
  },
})
