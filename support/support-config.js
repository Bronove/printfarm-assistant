/*
 * Public support-page configuration.
 * Fill only links and QR files that you own and have verified.
 */
window.SUPPORT_CONFIG = {
  projectName: "打印农场助手",
  projectNote: "非 Bambu Lab 官方项目",
  githubRepo: "Bronove/printfarm-assistant",
  communityDataUrl: "community-data.json",
  plansPageUrl: "https://afdian.com/a/printfarm-assistant/plan",
  plans: [
    {
      name: "一桶方便面",
      price: "6.6",
      note: "随手支持",
      features: ["开发进展", "可选鸣谢墙", "不锁定功能"]
    },
    {
      name: "一杯咖啡",
      price: "19.9",
      note: "持续关注",
      features: ["版本提醒", "公开问卷", "可选鸣谢墙"]
    },
    {
      name: "内测同行",
      price: "49",
      note: "参与测试",
      features: ["研发测试包", "测试清单", "反馈优先复核"]
    },
    {
      name: "深度共建",
      price: "99",
      note: "参与方向",
      features: ["功能投票", "月度验证场景", "特别感谢"]
    }
  ],
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
