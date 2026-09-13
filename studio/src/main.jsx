import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import "./styles.css";
import "./dark.css";
import "./micro-motion.css";
import "./controls.css";
import "./playing-track.css";
import "./design-system.css";
import "./linear-refinement.css";
import "./score-flow.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
