import React, { useEffect, useMemo, useState } from "react";
import mermaid from "mermaid";

let _inited = false;

function ensureInit() {
  if (_inited) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "strict"
  });
  _inited = true;
}

export default function Mermaid({ chart }) {
  const [svg, setSvg] = useState("");
  const [err, setErr] = useState("");
  const id = useMemo(() => `mmd-${Math.random().toString(36).slice(2)}`, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setErr("");
        setSvg("");
        ensureInit();
        const { svg: out } = await mermaid.render(id, chart);
        if (!cancelled) setSvg(out);
      } catch (e) {
        if (!cancelled) setErr(String(e?.message || e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (err) {
    return <div className="mermaidError">Mermaid render error: {err}</div>;
  }
  if (!svg) return <div className="mermaidLoading">Rendering diagram…</div>;

  // eslint-disable-next-line react/no-danger
  return <div className="mermaidWrap" dangerouslySetInnerHTML={{ __html: svg }} />;
}

