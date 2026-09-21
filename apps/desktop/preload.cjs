const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  notify(payload) {
    ipcRenderer.send('desktop-notify', payload)
  },
  appVersion: ipcRenderer.sendSync('desktop-app-version'),
  apiBase: process.env.SUPERCOURSE_API_BASE || '',
  openExternal(url) {
    return ipcRenderer.invoke('desktop-open-external', url)
  },
  showMain() {
    ipcRenderer.send('desktop-show-main')
  },
})
