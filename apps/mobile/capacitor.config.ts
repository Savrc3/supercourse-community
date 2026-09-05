import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'icu.savrc3.supercourse',
  appName: '超课表',
  webDir: '../web/dist',
  server: {
    androidScheme: 'https',
  },
}

export default config
