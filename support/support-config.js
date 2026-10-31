/*
 * Public support-page configuration.
 * Fill only links and QR files that you own and have verified.
 */
window.SUPPORT_CONFIG = {
  projectName: "打印农场助手",
  projectNote: "非 Bambu Lab 官方项目",
  githubRepo: "Bronove/printfarm-assistant",
  communityDataUrl: "community-data.json",
  methods: [
    {
      id: "afdian",
      label: "爱发电",
      short: "国内推荐",
      description: "查看月度支持方案或自选金额，适合使用微信与支付宝。",
      type: "link",
      url: "https://afdian.com/a/printfarm-assistant",
      actionLabel: "查看支持方案"
    },
    {
      id: "wechat",
      label: "微信赞赏",
      short: "扫码支持",
      description: "打开微信扫一扫，金额完全自愿。",
      type: "qr",
      image: "",
      alt: "打印农场助手的微信赞赏收款二维码",
      actionLabel: "查看赞赏码"
    },
    {
      id: "alipay",
      label: "支付宝",
      short: "扫码支持",
      description: "适合直接使用支付宝扫码支持。",
      type: "qr",
      image: "",
      alt: "打印农场助手的支付宝收款二维码",
      actionLabel: "查看收款码"
    },
    {
      id: "sponsors",
      label: "GitHub Sponsors",
      short: "面向开发者",
      description: "适合使用 GitHub 的开发者按月或一次性支持。",
      type: "link",
      url: "",
      actionLabel: "前往 GitHub Sponsors"
    }
  ]
};
