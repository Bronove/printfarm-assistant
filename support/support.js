(() => {
  const config = window.SUPPORT_CONFIG || { methods: [] };
  const list = document.querySelector("#methods-list");
  const dialog = document.querySelector("#qr-dialog");
  const qrImage = document.querySelector("#qr-image");
  const qrError = document.querySelector("#qr-error");
  const qrTitle = document.querySelector("#qr-title");

  const isConfigured = (method) => {
    if (method.type === "link") return Boolean(method.url);
    if (method.type === "qr") return Boolean(method.image);
    return false;
  };

  const createAction = (method) => {
    const label = document.createElement("span");
    label.className = "method-action";
    label.textContent = method.actionLabel || "继续";

    if (method.type === "link") {
      const link = document.createElement("a");
      link.className = "method-row";
      link.href = method.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.append(methodText(method), label);
      return link;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "method-row";
    button.append(methodText(method), label);
    button.addEventListener("click", () => openQr(method));
    return button;
  };

  const methodText = (method) => {
    const copy = document.createElement("span");
    copy.className = "method-copy";

    const title = document.createElement("span");
    title.className = "method-title";

    const name = document.createElement("strong");
    name.textContent = method.label;

    const short = document.createElement("small");
    short.textContent = method.short || "";
    title.append(name);
    if (method.short) title.append(short);

    const description = document.createElement("span");
    description.textContent = method.description || "";
    copy.append(title, description);
    return copy;
  };

  const openQr = (method) => {
    qrTitle.textContent = method.label;
    qrImage.alt = method.alt || `${method.label}收款二维码`;
    qrImage.hidden = false;
    qrError.hidden = true;
    qrImage.onerror = () => {
      qrImage.hidden = true;
      qrError.hidden = false;
    };
    qrImage.src = method.image;
    dialog.showModal();
  };

  const methods = (config.methods || []).filter(isConfigured);

  if (!methods.length) {
    const empty = document.createElement("div");
    empty.className = "methods-empty";
    const title = document.createElement("strong");
    title.textContent = "打赏入口正在接入";
    const body = document.createElement("p");
    body.textContent = "收款链接和二维码还没有绑定。为了安全，这里不会展示临时账户或伪造的收款码。软件仍会保持免费。";
    empty.append(title, body);
    list.append(empty);
    return;
  }

  methods.forEach((method) => list.append(createAction(method)));

  document.querySelector("[data-close-dialog]")?.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
