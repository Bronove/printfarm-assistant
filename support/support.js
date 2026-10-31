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

  const renderMethods = () => {
    const methods = (config.methods || []).filter(isConfigured);
    if (!methods.length) {
      const empty = document.createElement("div");
      empty.className = "methods-empty";
      const title = document.createElement("strong");
      title.textContent = "打赏入口正在接入";
      const body = document.createElement("p");
      body.textContent = "收款链接和二维码尚未绑定。这里不会展示临时账户或伪造收款码，软件仍会保持免费。";
      empty.append(title, body);
      list.append(empty);
      return;
    }
    methods.forEach((method) => list.append(createAction(method)));
  };

  const fetchJson = async (url, timeout = 8000) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      window.clearTimeout(timer);
    }
  };

  const initial = (name) => {
    const text = String(name || "?").trim();
    return text ? Array.from(text)[0].toUpperCase() : "?";
  };

  const createAvatar = (entry) => {
    const frame = document.createElement("span");
    frame.className = "avatar";
    frame.textContent = initial(entry.name || entry.login);
    if (!entry.avatarUrl) return frame;

    const image = document.createElement("img");
    image.src = entry.avatarUrl;
    image.alt = "";
    image.loading = "lazy";
    image.width = 42;
    image.height = 42;
    image.addEventListener("load", () => {
      frame.textContent = "";
      frame.append(image);
    }, { once: true });
    return frame;
  };

  const renderContributors = (entries) => {
    const listElement = document.querySelector("#contributors-list");
    const status = document.querySelector("#contributors-status");
    listElement.replaceChildren();
    if (!entries.length) {
      status.textContent = "贡献记录正在整理，欢迎提交第一个可核实的贡献。";
      return;
    }
    status.textContent = `共 ${entries.length} 位代码贡献者 · 按 GitHub 公开提交数排序`;
    entries.forEach((entry, index) => {
      const item = document.createElement("li");
      item.className = "contributor-row";

      const rank = document.createElement("span");
      rank.className = "contributor-rank";
      rank.textContent = String(index + 1).padStart(2, "0");

      const identity = document.createElement("span");
      identity.className = "contributor-identity";
      identity.append(createAvatar(entry));
      const copy = document.createElement("span");
      const name = document.createElement(entry.profileUrl ? "a" : "strong");
      name.textContent = entry.name || entry.login || "匿名贡献者";
      if (entry.profileUrl) {
        name.href = entry.profileUrl;
        name.target = "_blank";
        name.rel = "noopener noreferrer";
      }
      const handle = document.createElement("small");
      handle.textContent = entry.login ? `@${entry.login}` : "项目贡献者";
      copy.append(name, handle);
      identity.append(copy);

      const badge = document.createElement("span");
      badge.className = "contribution-badge";
      badge.textContent = "代码贡献";

      const count = document.createElement("span");
      count.className = "contribution-count";
      const value = document.createElement("strong");
      value.textContent = String(entry.contributions || 0);
      const unit = document.createElement("small");
      unit.textContent = "次提交";
      count.append(value, unit);

      item.append(rank, identity, badge, count);
      listElement.append(item);
    });
  };

  const renderThanks = (entries) => {
    if (!entries.length) return;
    const section = document.querySelector("#special-thanks");
    const grid = document.querySelector("#thanks-grid");
    entries.forEach((entry) => {
      const card = document.createElement("article");
      const label = document.createElement("span");
      label.textContent = entry.label || "特别贡献";
      const name = document.createElement(entry.link ? "a" : "strong");
      name.textContent = entry.name || "匿名贡献者";
      if (entry.link) {
        name.href = entry.link;
        name.target = "_blank";
        name.rel = "noopener noreferrer";
      }
      const note = document.createElement("p");
      note.textContent = entry.note || "";
      card.append(label, name, note);
      grid.append(card);
    });
    section.hidden = false;
  };

  const renderSupporters = (entries) => {
    const section = document.querySelector("#supporters");
    const wall = document.querySelector("#supporters-wall");
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "supporters-empty";
      empty.textContent = "还没有公开姓名的打赏者。支持时可以选择匿名，公开名单只会在本人同意后加入。";
      wall.append(empty);
      return;
    }
    entries.forEach((entry) => {
      const card = document.createElement("article");
      const avatar = createAvatar(entry);
      const copy = document.createElement("span");
      const name = document.createElement(entry.link ? "a" : "strong");
      name.textContent = entry.name || "匿名支持者";
      if (entry.link) {
        name.href = entry.link;
        name.target = "_blank";
        name.rel = "noopener noreferrer";
      }
      const note = document.createElement("small");
      note.textContent = entry.note || "感谢支持";
      copy.append(name, note);
      card.append(avatar, copy);
      wall.append(card);
    });
  };

  const loadCommunity = async () => {
    let data = { fallbackContributors: [], specialThanks: [], supporters: [] };
    try {
      data = await fetchJson(config.communityDataUrl || "community-data.json");
    } catch {
      // Keep safe local fallbacks.
    }

    const api = `https://api.github.com/repos/${config.githubRepo}/contributors?per_page=100`;
    try {
      const github = await fetchJson(api);
      const contributors = github
        .filter((entry) => entry.type === "User" && !entry.login.endsWith("[bot]"))
        .map((entry) => ({
          name: entry.login,
          login: entry.login,
          contributions: entry.contributions,
          avatarUrl: entry.avatar_url,
          profileUrl: entry.html_url,
        }));
      renderContributors(contributors.length ? contributors : data.fallbackContributors);
    } catch {
      renderContributors(data.fallbackContributors || []);
      document.querySelector("#contributors-status").textContent += " · GitHub 暂时不可用，显示本地快照";
    }
    renderThanks(data.specialThanks || []);
    renderSupporters(data.supporters || []);
  };

  renderMethods();
  void loadCommunity();

  document.querySelector("[data-close-dialog]")?.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
