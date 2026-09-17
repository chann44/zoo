"use client";

import { useEffect, useRef } from "react";
import RFB from "@novnc/novnc";



export default function Desktop() {
  const desktopRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = desktopRef.current;

    if (!container) {
      return;
    }

    const url = "ws://localhost:8000/ws";

    console.log("Connecting:", url);

    const rfb = new RFB(container, url);
    let cancelled = false;

    rfb.scaleViewport = true;
    rfb.resizeSession = false;

    rfb.addEventListener("connect", () => {
      if (cancelled) {
        rfb.disconnect();
        return;
      }
      console.log("VNC CONNECTED");
    });

    rfb.addEventListener("disconnect", (event) => {
      console.log("VNC DISCONNECTED", event);
    });

    rfb.addEventListener("securityfailure", (event) => {
      console.error("VNC SECURITY FAILURE", event);
    });

    return () => {
      cancelled = true;
      rfb.disconnect();
    };
  }, []);

  return (
    <div style={{ position: "fixed", inset: 0, background: "black" }}>
      <div ref={desktopRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}