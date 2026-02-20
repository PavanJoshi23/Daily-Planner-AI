import React from "react";

export default function JsonBlock({ value }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="jsonBlock">
      <code>{text}</code>
    </pre>
  );
}

