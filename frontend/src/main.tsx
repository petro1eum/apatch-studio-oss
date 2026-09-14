import React from "react";
import ReactDOM from "react-dom/client";

import { OutsideInApp } from "./OutsideInApp";
import "./styles.css";
import "./outside-in.css";
import "./trustchain-theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <OutsideInApp />
  </React.StrictMode>,
);
