# 打赏与贡献榜

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

## 贡献榜数据

- GitHub 代码贡献由页面的 GitHub Contributors API 自动读取。
- `community-data.json` 中的 `fallbackContributors` 是 API 不可用时的本地快照。
- `specialThanks` 用于代码以外的测试、问题复现、文档、翻译和设计贡献。
- `supporters` 只放明确同意公开的打赏者，默认不展示金额。

示例：

```json
{
  "specialThanks": [
    {
      "name": "用户名",
      "label": "问题复现",
      "note": "提交了 3MF、日志和可复现步骤",
      "link": "https://github.com/用户名"
    }
  ],
  "supporters": [
    {
      "name": "用户名",
      "note": "感谢支持",
      "link": "",
      "avatarUrl": ""
    }
  ]
}
```

未获得本人同意的名字不要公开。榜单不得按打赏金额售卖排名。

## 本地预览

在仓库根目录运行：

```powershell
python -m http.server 4173
```

然后访问：

```text
http://127.0.0.1:4173/support/
```
