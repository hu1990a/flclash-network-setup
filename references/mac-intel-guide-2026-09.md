# macOS 完整操作与排障

本说明同时适用于 Intel 与 Apple Silicon。订阅优化逻辑与 Windows 相同，平台差异集中在安装包、网络服务名、IPv6 命令和 shell 环境变量。

## 1. 确认芯片与安装包

```bash
uname -m
```

- `x86_64`：选择 macOS amd64/x64 安装包。
- `arm64`：选择 macOS arm64 安装包。

从 FlClash 官方 GitHub Releases 获取与芯片匹配的当前版本，不在通用 Skill 中固定版本号或第三方镜像。若 macOS 提示来源不明，优先在“系统设置 → 隐私与安全性”中核对开发者信息并选择仍要打开；向导不自动绕过 Gatekeeper。

## 2. 只读摸底

```bash
bash scripts/setup-mac.sh audit
```

脚本检查架构、FlClash、活动订阅、混合端口和 Python。若无法自动定位订阅，可显式设置 `FLCLASH_PROFILE` 为当前订阅 YAML；报告不显示用户目录绝对路径。

## 3. 选择 CLI 时区

CLI 时区写入 `~/.zshrc` 的受控配置块，不改变菜单栏时钟、日历或会议时间。向导给出两个选择：

1. `America/Puerto_Rico`：固定慢北京时间 12 小时，方便换算；可能与代理出口不一致。
2. 与实测代理出口一致（推荐）：通过 `FLCLASH_PROXY_TIMEZONE` 或命令参数传入 IANA 时区，减少位置与时区冲突，并遵循当地夏令时。

用户未选择前不写入 `TZ`。系统时区默认保持不变。

## 4. 优化订阅

```bash
python3 scripts/replace-config.py "$FLCLASH_PROFILE" --port <检测到的端口> --dry-run
python3 scripts/replace-config.py "$FLCLASH_PROFILE" --port <检测到的端口>
```

脚本自动识别当前订阅的节点域名，只替换 `proxies:` 之前的通用配置，并保护节点、策略组和规则。每个订阅都要单独备份、写入和验证。

## 5. 应用本机设置

显式传入选择后的 IANA 时区：

```bash
bash scripts/setup-mac.sh apply <用户选择的IANA时区>
```

也可以先设置已检测的出口时区，再进入二选一交互：

```bash
export FLCLASH_PROXY_TIMEZONE="America/Los_Angeles"
bash scripts/setup-mac.sh apply
```

脚本在 `~/.zshrc` 中维护带 `flclash-skill env begin/end` 标记的单一配置块，重复执行不会不断追加代理变量。配置包括 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、官方 API 地址和 `TZ`。

## 6. 禁用活动网络服务的 IPv6

先查看真实服务名：

```bash
networksetup -listallnetworkservices
```

脚本会询问要处理的服务，例如 Wi-Fi、Ethernet 或 iPhone USB，再执行：

```bash
sudo networksetup -setv6off "<网络服务名称>"
networksetup -getinfo "<网络服务名称>"
```

不要假设所有机器的服务都叫 Wi-Fi。恢复命令是：

```bash
sudo networksetup -setv6automatic "<网络服务名称>"
```

## 7. FlClash 人工操作

1. 开启 TUN；首次提示辅助工具权限时输入本机密码授权。
2. 开启系统代理。
3. 关闭经过本地优化订阅的自动更新。
4. 从菜单栏完全退出 FlClash，再重新打开。
5. 不要点击刷新订阅。
6. 重开终端，或执行 `source ~/.zshrc` 让新环境变量生效。

## 8. 手机热点

Android 热点优先把 APN 协议设为 IPv4。iPhone 无法直接修改时，通过电脑侧 IPv6 验证判断；仍有 IPv6 时改用稳定 Wi-Fi 或咨询运营商。

## 9. 安装与运行 ipcheck

安装前获得联网和依赖安装授权：

```bash
bash scripts/install-ipcheck-macos.sh
```

安装脚本负责检查 Python 版本和用户级命令目录，不在指南中固定过期的 Python 安装包地址。安装不代表允许发送公网 IP；运行 `ipcheck` 前还要单独说明第三方查询和隐私风险并取得同意。

## 10. 验收

```bash
bash scripts/setup-mac.sh verify
```

补充确认：FlClash 使用正确架构、DNS fake-IP 生效、实际混合端口匹配环境变量、所选网络服务 IPv6 已关闭、TUN 与系统代理开启、CLI `TZ` 与用户选择一致、订阅受保护尾部未改变。

## 11. 常见问题

- 节点全部 `TIMEOUT`：检查自动识别的节点域名与 `nameserver-policy`。
- Safari 能联网但终端不能：核对代理环境变量端口，随后重新加载 `~/.zshrc`。
- 配置重新变回原样：关闭订阅自动更新，不要刷新。
- ipcheck 安装后命令不存在：重开终端，并检查 Python 用户级 `bin` 是否进入 PATH。
- SSL 查询偶发失败：保留其他检查结果，确认服务恢复后最多重试一次。
- 需要恢复：按 `references/privacy-and-rollback.md` 恢复订阅备份、IPv6 和受控环境变量块。
