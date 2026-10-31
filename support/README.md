# 打赏页

这是打印农场助手的静态打赏页，部署地址为：

```text
https://bronove.github.io/printfarm-assistant/support/
```

## 绑定收款方式

编辑 `support-config.js`：

- 爱发电：填写 `id: "afdian"` 的 `url`。
- GitHub Sponsors：填写 `id: "sponsors"` 的 `url`。
- 微信或支付宝：把收款码放进 `assets/`，并填写对应的 `image` 路径。

空渠道会自动隐藏。没有配置任何渠道时，页面会显示“打赏入口正在接入”，不会展示假二维码。

## 本地预览

在仓库根目录运行：

```powershell
python -m http.server 4173
```

然后访问：

```text
http://127.0.0.1:4173/support/
```
