# FlClash 通用优化配置详解

本说明对应 `scripts/replace-config.py` 实际生成的配置。脚本是配置真值；这里帮助用户看懂改了什么，不提供绑定某个订阅商的固定复制块。

## 自动生成配置结构

下面是脱敏结构示例。`<检测到的端口>` 和 `<自动识别节点域名>` 会在运行时替换，不需要用户手填：

```yaml
mixed-port: <检测到的端口>
ipv6: false
udp: true
allow-lan: false
bind-address: '*'
mode: rule
log-level: info
unified-delay: true
experimental:
  ignore-resolve-fail: true
dns:
  enable: true
  listen: '127.0.0.1:1053'
  ipv6: false
  use-hosts: true
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  default-nameserver:
    - 223.5.5.5
    - 119.29.29.29
    - 1.1.1.1
  nameserver:
    - 1.1.1.1
    - 8.8.8.8
    - 223.5.5.5
  fallback:
    - 8.8.8.8
    - tls://1.1.1.1
  fallback-filter:
    geoip: true
    geoip-code: CN
    ipcidr:
      - 240.0.0.0/4
      - 0.0.0.0/32
      - 127.0.0.1/32
  nameserver-policy:
    'domain:<自动识别节点域名>':
      - 119.29.29.29
      - 223.5.5.5
  fake-ip-filter:
    - <由脚本维护的兼容列表>
```

随后接回订阅原有的 `proxies:`、`proxy-groups:` 和 `rules:`。这三段属于受保护尾部，不允许重写。

## 每项作用

| 配置 | 作用 |
|---|---|
| `mixed-port` | 使用 FlClash 实际混合端口，不假设所有电脑都是 7890 |
| 顶层与 DNS `ipv6: false` | 让 Mihomo 配置优先使用 IPv4并停止返回 AAAA；它不等于关闭 Windows/macOS 系统 IPv6。Windows 默认保留绑定并设置 IPv4 优先，macOS 默认保持自动配置 |
| `enhanced-mode: fake-ip` | 让 Mihomo 接管域名解析并按规则分流 |
| `fake-ip-range: 198.18.0.1/16` | 使用基准测试保留网段，便于识别 fake-IP 是否生效 |
| `default-nameserver` | 解析 DNS 服务器自身的域名 |
| `nameserver` | 默认解析入口；裸 IP DNS 一般是普通 DNS，不应统称为加密 DNS |
| `fallback` | 默认解析失败或命中过滤条件时提供备用解析 |
| `fallback-filter` | 依据地区和保留地址决定是否采用 fallback 结果 |
| `nameserver-policy` | 让自动识别节点域名走稳定的指定 DNS，减少节点全部超时 |
| `fake-ip-filter` | 为局域网、NTP、游戏平台、音乐和连通性检测保留真实解析兼容性 |

## 自动适配与隐私

- 脚本只扫描 `proxies:` 区域中的 `server` 字段，用于自动识别节点域名。
- IP 形式的节点不会被误当成域名；无法识别时要求用户明确提供 `--node-domain`。
- 运行结果只显示数量、状态、备份文件名和哈希，不显示节点名、服务器、密码、订阅 URL 或公网 IP。
- 公开分享版不包含订阅商域名、固定中转地址或用户目录。

## 为什么不直接复制固定配置

- 不同订阅的节点域名不同，固定 `nameserver-policy` 容易导致整组节点 `TIMEOUT`。
- 静态 `hosts` 会把域名固定到某个 IP，地址变化后可能失效，因此不作为通用默认项。
- `cfw-latency-*` 和 `cfw-conn-break-strategy` 属于旧前端风格参数，不作为当前 Mihomo 通用核心配置。
- 固定 DoH IP、证书和中转域名可能随订阅变化，必须从当前环境检测或由用户明确提供。

## 安全应用

先运行 dry-run：

```powershell
python scripts/replace-config.py "<profile.yaml>" --port <检测到的端口> --dry-run
```

确认能识别节点域名、受保护尾部数量和哈希后再写入：

```powershell
python scripts/replace-config.py "<profile.yaml>" --port <检测到的端口>
```

写入前会建立同目录备份。完成后完全退出并重开 FlClash，不要刷新远端订阅；最后运行平台 Verify 和已授权的 ipcheck。

## 常见排障

1. 节点全部 `TIMEOUT`：确认自动识别的节点域名数量大于零，并检查这些域名是否进入 `nameserver-policy`。
2. fake-IP 未生效：检查 DNS 覆写是否启用，以及 A 记录是否落在 `198.18.0.0/16`。
3. 海外网站能开、终端不能联网：核对实际混合端口与 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`。
4. 保存后配置恢复原样：关闭该订阅自动更新，不要点击刷新订阅。
5. 需要回滚：完全退出 FlClash，用脚本生成的备份恢复同名订阅文件，再重新打开。
