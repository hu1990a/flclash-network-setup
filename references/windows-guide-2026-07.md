# Windows 完整操作与排障

本说明面向 PowerShell 用户。脚本会从当前电脑读取 FlClash 资料目录、活动订阅和混合端口，不需要复制其他人的固定配置。

## 1. 只读摸底

在普通 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1 -Mode Audit
```

确认输出包含 FlClash、活动订阅、订阅数量、混合端口、系统代理、TUN、物理网卡 IPv6、Python 和 ipcheck 状态。摸底阶段不修改配置。

## 2. 先了解 CLI 时区选项（暂不设置）

脚本先解释 CLI 时区不改变任务栏时钟，并说明两个可选模式：

1. `America/Puerto_Rico`：固定慢北京时间 12 小时，方便换算；可能与代理出口不一致。
2. 与实测代理出口一致（推荐）：例如洛杉矶使用 `America/Los_Angeles`，减少位置与时区冲突，并自动遵循夏令时。

这里只记录用户偏好，不写入 `TZ`。系统时区默认保持不变；最终 CLI 时区要等第 4 步批测并确认节点后再决定。

## 3. 优化订阅

先执行 dry-run，再写入：

```powershell
python scripts/replace-config.py "<profile.yaml>" --port <检测到的端口> --dry-run
python scripts/replace-config.py "<profile.yaml>" --port <检测到的端口>
```

脚本只替换顶层 `proxies:` 之前的通用配置。节点、策略组和规则属于受保护尾部；写入前后必须保持数量与哈希一致。每个订阅单独建立备份。

## 4. 先批测节点

在写入 CLI 时区前，先按 [节点稳定性与安全性批测指南](node-testing-guide.md) 对用户允许地区的候选执行至少 3 轮延迟测试。获得单独的数据外发授权后再运行 ipcheck 安全检查。脚本默认恢复原节点并给出最多 3 个推荐；用户确认最终节点后才进入下一步。

## 5. 确认节点后设置 CLI 时区并应用本机设置

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1 `
  -Mode Apply -CliTimeZone <用户选择的IANA时区> `
  -IPv6Mode PreferIPv4 [-RestoreAdapterIPv6] [-InstallIpcheck] [-UsesMobileHotspot]
```

脚本会设置当前用户的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、官方 API 地址和 `TZ`，并把代理守卫安装到 Windows PowerShell 和 PowerShell 7 的用户 Profile。默认 `PreferIPv4` 会备份原注册表值与网卡绑定状态，再把 `DisabledComponents` 设置为 `0x20`；它保留 IPv6，需要管理员权限和一次 Windows 重启。微软推荐优先 IPv4，而不是从网卡取消绑定 IPv6：[官方说明](https://learn.microsoft.com/zh-cn/troubleshoot/windows-server/networking/configure-ipv6-in-windows)。

旧版 Skill 已关闭活动网卡 IPv6 时，审计会显示绑定异常。用户同意恢复后加 `-RestoreAdapterIPv6`。只有实测发现 IPv6 绕过代理且用户明确要求时，才使用 `-IPv6Mode StrictDisable -AdapterName "<网卡名>"`；`Keep` 模式不修改系统 IP 策略。

以后每次打开新 PowerShell，守卫会从 FlClash 当前状态重新读取 `mixed-port`。端口更改后会自动刷新大写、小写代理变量。`claude` 和 `codex` 每次启动前都要确认该端口确由 FlClash 状态给出且正在监听；无法确认时显示 `FAIL-CLOSED` 并停止，避免 CLI 在未知网络状态下直连。仅有一个程序监听常用端口不算确认。可运行 `proxy_on` 重新检测，或用 `proxy_off` 清空本会话代理变量并锁定两个 CLI。该守卫只作用于新打开的 PowerShell，不接管已经运行的桌面应用。

如果使用非交互模式，必须显式传入 `-CliTimeZone`，或在实测出口后传入 `-ProxyTimeZone`，否则脚本停止。

## 6. FlClash 人工操作

1. 在 FlClash 中打开 TUN，并允许首次出现的辅助服务授权。
2. 打开系统代理。
3. 关闭经过本地优化订阅的自动更新。
4. 从系统托盘完全退出 FlClash，再重新打开。
5. 不要点击刷新订阅，否则远端内容可能覆盖本地优化。
6. 关闭并重新打开 PowerShell、Codex 或其他 CLI，使用户环境变量生效。

## 7. 手机热点

未使用手机热点时跳过。使用 Android 热点时，将当前 APN 协议设为 IPv4，然后重新开关热点并让电脑重连。iPhone 通常不能直接改 APN 协议；让 Agent 检测电脑侧 IPv6，仍有 IPv6 时改用稳定 Wi-Fi 或咨询运营商。

## 8. ipcheck

安装和运行属于两个授权：

```powershell
python -m pip install --user --upgrade ai-ipcheck
ipcheck
```

完整检测会把运营商公网 IP 与代理出口 IP 发给第三方查询服务。运行前必须让用户单独同意，报告中用 `[REDACTED_IP]` 隐藏真实地址。

部分 Windows 版本的 ipcheck 无法识别系统代理、TUN 或正确显示 IANA 偏移。用宿主机只读检查和 Python `zoneinfo` 交叉验证，不因显示错误重复改配置。

## 9. 日常自动守卫（可选）

完整配置通过后，可让 Agent 安装当前用户后台守卫。安装器优先注册计划任务；普通用户权限被系统拒绝时，会自动改用当前用户“启动”目录，不要求为了后台提醒而取得管理员权限：

```powershell
# 默认只检查本机端口和 TUN
powershell -ExecutionPolicy Bypass -File scripts/install-windows-network-guard.ps1 -Mode Install

# 单独同意把出口 IP 发给 ifconfig.co 后才使用
powershell -ExecutionPolicy Bypass -File scripts/install-windows-network-guard.ps1 -Mode Install -AllowExternalIpCheck
```

正常时不会打扰你。异常连续出现两次才发 Windows 通知，通知会告诉你“推荐操作”和“原因”。它不会自己切节点、改订阅或关闭 IPv6。用 `-Mode CheckNow` 立即检查，用 `-Mode TestNotification` 查看安全演示通知；用 `Pause`、`Resume`、`Status`、`Uninstall` 管理。`Status` 的 `LaunchMethod` 会显示 `ScheduledTask` 或 `StartupFolder`。Windows 通知被关闭时，检查仍会运行，但通知验收记为 `PENDING`。

## 10. 验收

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1 -Mode Verify
```

还要确认：DNS A 记录落在 `198.18.0.0/16`、实际端口正在监听、TUN 与系统代理已开启、CLI `TZ` 等于用户选择、FlClash 重启时间晚于配置写入时间，以及两个 PowerShell Profile 均已安装守卫。默认 IP 策略还要确认注册表是 `0x20`，并执行 `netsh interface ipv6 show prefixpolicies`：`::ffff:0:0/96` 的优先级必须高于 `::/0`。普通 `ping bing.com` 应优先显示 IPv4；它只是辅助证据，仍要结合出口检查。自动化测试必须覆盖端口变化后变量更新、未知监听器不被误认、端口关闭时 Claude/Codex 未被调用。

## 11. 常见问题

- 节点全部 `TIMEOUT`：检查节点域名是否被自动识别并进入 `nameserver-policy`。
- 配置保存后恢复：关闭订阅自动更新，不要刷新订阅。
- 终端不能联网：核对 FlClash 实际混合端口与三个代理环境变量。
- `FAIL-CLOSED`：先确认 FlClash 已启动并加载当前订阅，再运行 `proxy_on`。仍失败时检查 `shared_preferences.json` 中是否存在有效 `mixed-port`，不要临时硬编码一个未知端口。
- ipcheck 报 DNS 获取失败：单独运行 DNS A 记录查询；能解析不代表工具能枚举系统 DNS。
- ipcheck 报时区偏移异常：用 `zoneinfo` 核对 IANA 时区。
- 需要恢复：按 `references/privacy-and-rollback.md` 恢复订阅备份、IPv6 和用户环境变量。
