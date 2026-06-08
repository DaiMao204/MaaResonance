import type { FullConfig } from '@nekosu/maa-tools'

const config: FullConfig = {
  cwd: import.meta.dirname,
  maaCache: '.codex_deps/maa-tools',
  maaLogDir: '.codex_deps/maa-log',
  maaVersion: '5.10.5',
  interfacePath: 'assets/interface.json',
  check: {
    override: {
      // 忽略 mpe-config 带来的报错
      // ignore warning caused by mpe-config
      // 'mpe-config': 'ignore'
      'duplicate-next': 'ignore'
    }
  }
}

export default config
