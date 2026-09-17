# flclash-network-setup

面向小白的 FlClash 一次性向导。它会从只读摸底开始，引导用户完成订阅配置备份与 DNS 优化、本机代理环境变量、CLI 时区、IPv6、TUN、手机热点以及 `ai-ipcheck` 检测，并输出脱敏验收报告。完成后退出，不驻留后台。

## 安装

```bash
npx skills add https://github.com/hu1990a/flclash-network-setup --skill flclash-network-setup
```

也可以将仓库放入 Agent 支持的 Skills 目录，并确认入口文件为 `SKILL.md`。

## 使用方式

对 Agent 说：

```text
使用 flclash-network-setup 检查并配置我的 FlClash 网络环境。
```

Skill 会先检查当前状态，再一次性收集需要用户决定或授权的项目。完整流程和安全边界见 [SKILL.md](SKILL.md)。

## 主要能力

- 自动发现 FlClash 配置、订阅和本地代理端口。
- 批量执行多轮节点延迟和出口安全检测，恢复原节点后给出可解释的推荐，再由用户选择最终节点。
- Windows PowerShell 启动时自动适配 FlClash 端口；无法确认代理时阻止 Claude/Codex CLI 直连启动。
- 逐订阅备份并优化 DNS，同时保护节点、策略组和规则内容；全局解析池与订阅域名全部走加密 DoH，固定 CN 白名单走明文国内 DNS，不引入任何明文境外查询。
- 区分 CLI 时区与系统时区，并根据实际代理出口提供建议。
- Windows 默认保留 IPv6 并设置 IPv4 优先，macOS 默认保留自动 IPv6；只有实测旁路时才提供严格关闭模式。
- 检查 Windows/macOS 的代理、IPv4/IPv6 出口、TUN 和热点环境。
- 只在用户主动运行向导或 `Verify` 时按需复检；不安装计划任务、开机启动项、LaunchAgent，不做定时检测或系统弹窗。
- 在单独获得安装与数据外发授权后安装、运行 `ai-ipcheck`。
- 输出 `PASS / PENDING / FAIL / NOT_APPLICABLE` 验收结果和恢复方法。

## 隐私与安全

- 不应输出或保存订阅 URL、节点密码、UUID、Cookie、令牌或真实公网 IP。
- 修改配置前必须 dry-run 和备份，写入后验证受保护内容没有变化。
- 安装依赖、运行公网 IP 检测、修改系统时区和管理员操作需要分别授权。
- `ai-ipcheck` 完整检测会把公网出口 IP 发送给第三方查询服务；Skill 会在运行前说明服务和风险。

## 目录

- `SKILL.md`：Skill 入口与完整工作流。
- `scripts/`：Windows/macOS 配置、订阅优化、节点批测和出口推荐脚本。
- `references/`：小白指南、平台说明、参数解释与回滚方法。
- `tests/`：脱敏、配置保护和引导规则测试。

## License

[MIT](LICENSE)
