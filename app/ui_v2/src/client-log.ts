const endpoint = (() => {
  const configured = import.meta.env.VITE_OCR_ENDPOINT
    ?? "http://127.0.0.1:4180/api/ocr";
  try {
    return `${new URL(configured).origin}/api/log`;
  } catch {
    return "http://127.0.0.1:4180/api/log";
  }
})();

export function logLocal(category: string, message: string, data?: unknown) {
  void fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, message, data }),
    keepalive: true,
  }).catch(() => {
    // Local logging must never break the primary UI action.
  });
}

export function installClientLogging() {
  window.addEventListener("error", (event) => {
    logLocal("界面错误", event.message, {
      source: event.filename,
      line: event.lineno,
      column: event.colno,
      stack: event.error instanceof Error ? event.error.stack : "",
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    logLocal("界面错误", "未处理的 Promise 异常", {
      reason: reason instanceof Error ? reason.message : String(reason),
      stack: reason instanceof Error ? reason.stack : "",
    });
  });
  logLocal("界面", "前端启动");
}
