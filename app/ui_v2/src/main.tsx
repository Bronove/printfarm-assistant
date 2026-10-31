import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installClientLogging } from "./client-log";
import "./styles.css";

installClientLogging();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
