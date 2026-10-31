import { useEffect, useRef, useState } from "react";
import Button from "./ui/Button";
import { SparkIcon, UploadIcon } from "./ui/icons";

type OcrState =
  | { phase: "idle" }
  | { phase: "reading"; fileName: string }
  | { phase: "done"; fileName: string; note?: string }
  | { phase: "error"; fileName: string; message: string };

const EXAMPLES = [
  "层高 0.16，填充 15%，隐藏 Z 缝",
  "H2S，支撑只放打印板，自动摆盘",
  "关闭支撑，保留原朝向，填充 20%",
];

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

async function recognizeImage(file: File): Promise<{ text: string; note?: string }> {
  const endpoint = import.meta.env.VITE_OCR_ENDPOINT ?? "http://127.0.0.1:4180/api/ocr";
  const image = await readFileAsDataUrl(file);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || payload.note || "OCR 服务暂时不可用");
  }
  return { text: String(payload.text ?? ""), note: payload.note || undefined };
}

export default function SmartCommandBar({
  value,
  summaries,
  onChange,
}: {
  value: string;
  summaries: string[];
  onChange: (value: string) => void;
}) {
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [ocrState, setOcrState] = useState<OcrState>({ phase: "idle" });
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const handleImages = async (files: File[]) => {
    const images = files.filter((file) => file.type.startsWith("image/"));
    if (!images.length) return;
    const file = images[0];
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(file));
    const displayName = images.length === 1 ? file.name : `${images.length} 张图片`;
    setOcrState({ phase: "reading", fileName: displayName });
    try {
      const results = [];
      for (const image of images) results.push(await recognizeImage(image));
      const text = results.map((result) => result.text).filter(Boolean).join("\n");
      const note = results.map((result) => result.note).filter(Boolean).join("；");
      onChange(text);
      setOcrState({ phase: "done", fileName: displayName, note });
    } catch (error) {
      setOcrState({
        phase: "error",
        fileName: displayName,
        message: error instanceof Error ? error.message : "图片识别失败",
      });
    }
  };

  return (
    <section className="command-panel" aria-labelledby="command-title">
      <h2 id="command-title" className="visually-hidden">一句话修改参数</h2>
      <div className="command-panel__heading">
        <span
          className="command-help"
          onMouseEnter={() => setHelpOpen(true)}
          onMouseLeave={() => setHelpOpen(false)}
          onFocus={() => setHelpOpen(true)}
          onBlur={() => setHelpOpen(false)}
        >
          <button
            type="button"
            className="command-help__trigger"
            aria-label="一句话修改参数说明"
            aria-expanded={helpOpen}
            onClick={() => setHelpOpen((open) => !open)}
          >
            <SparkIcon />
          </button>
          {helpOpen ? (
            <span className="command-help__popover" role="tooltip">
              说参数，或输入一句话同时修改多个参数；右侧设置会随输入即时变化，也可以贴图识别文字。
            </span>
          ) : null}
        </span>
      </div>

      <div className="command-composer">
        {previewUrl ? (
          <img className="command-preview" src={previewUrl} alt="待识别截图" />
        ) : null}
        <textarea
          value={value}
          rows={2}
          aria-label="一句话参数和图片识别口令"
          placeholder="说参数，或输入一句话修改多个参数"
          onChange={(event) => onChange(event.target.value)}
          onPaste={(event) => {
            const image = Array.from(event.clipboardData.items)
              .find((item) => item.type.startsWith("image/"))
              ?.getAsFile();
            if (image) {
              event.preventDefault();
              void handleImages([image]);
            }
          }}
        />
        <div className="command-actions">
          <Button
            variant="ghost"
            leadingIcon={<UploadIcon />}
            onClick={() => imageInputRef.current?.click()}
            loading={ocrState.phase === "reading"}
          >
            图片识别文字
          </Button>
          <input
            ref={imageInputRef}
            className="visually-hidden"
            type="file"
            accept="image/*"
            multiple
            onChange={(event) => {
              void handleImages(Array.from(event.target.files ?? []));
              event.currentTarget.value = "";
            }}
          />
          <span className="command-live" aria-live="polite">
            {ocrState.phase === "reading"
              ? `正在识别 ${ocrState.fileName}…`
              : ocrState.phase === "done"
                ? `已识别 ${ocrState.fileName}${ocrState.note ? ` · ${ocrState.note}` : ""}`
                : ocrState.phase === "error"
                  ? `图片已加入，OCR 未连接：${ocrState.message}`
                  : summaries.length
                    ? `已同步：${summaries.join(" · ")}`
                    : "输入参数后，对应设置会立即更新"}
          </span>
          <span
            className="command-examples-wrap"
            onMouseEnter={() => setExamplesOpen(true)}
            onMouseLeave={() => setExamplesOpen(false)}
            onFocus={() => setExamplesOpen(true)}
            onBlur={() => setExamplesOpen(false)}
          >
            <button
              type="button"
              className="command-example-trigger"
              aria-expanded={examplesOpen}
              aria-haspopup="true"
              onClick={() => setExamplesOpen((open) => !open)}
            >
              示例
            </button>
            {examplesOpen ? (
              <span className="command-examples" role="group" aria-label="示例口令">
                {EXAMPLES.map((example) => (
                  <button
                    type="button"
                    key={example}
                    onClick={() => {
                      onChange(example);
                      setExamplesOpen(false);
                    }}
                  >
                    {example}
                  </button>
                ))}
              </span>
            ) : null}
          </span>
        </div>
      </div>
    </section>
  );
}
