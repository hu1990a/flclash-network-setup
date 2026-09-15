# 隐私、权限与回滚

## 默认脱敏

可以显示的通用地址：

- `127.0.0.1`：本机回环地址。
- `198.18.0.0/16`：fake-IP 测试网段。
- `1.1.1.1`、`8.8.8.8`、`119.29.29.29`、`223.5.5.5`：公共 DNS。

默认隐藏：订阅 URL、节点服务器清单、密码、UUID、令牌、真实公网 IP、SSID、设备名、用户名和用户目录绝对路径。日志只保留订阅文件名、统计数量、状态与哈希。

## 回滚订阅

`replace-config.py` 会在原目录生成：

```text
<订阅文件名>.bak.<时间戳>
```

完全退出 FlClash 后，用备份覆盖对应订阅文件，再重新打开 FlClash。覆盖前核对文件名，不对整个配置目录执行批量删除或恢复。

## 恢复 IPv6

Windows 管理员 PowerShell：

```powershell
Enable-NetAdapterBinding -Name "<已修改的物理网卡名称>" -ComponentID ms_tcpip6
```

macOS：

```bash
sudo networksetup -setv6automatic "<网络服务名称>"
```

## 清除用户环境变量

Windows PowerShell：

```powershell
[Environment]::SetEnvironmentVariable('HTTP_PROXY',$null,'User')
[Environment]::SetEnvironmentVariable('HTTPS_PROXY',$null,'User')
[Environment]::SetEnvironmentVariable('ALL_PROXY',$null,'User')
[Environment]::SetEnvironmentVariable('TZ',$null,'User')
```

Windows 安装守卫时会先为已有的 `profile.ps1` 创建 `.bak.<时间戳>`。要停用守卫，关闭所有 Claude/Codex CLI，在 Windows PowerShell 与 PowerShell 7 的 Profile 中删除下面两个标记及其中内容，或用对应备份恢复，然后重新打开终端：

```text
# === flclash-skill windows env begin ===
# === flclash-skill windows env end ===
```

macOS 从 `~/.zshrc` 删除 `flclash-skill env begin/end` 标记之间的块，再重新打开终端。
