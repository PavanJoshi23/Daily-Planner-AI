import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Mermaid from "./Mermaid.jsx";

export default function MarkdownMessage({ content }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const m = /language-(\w+)/.exec(className || "");
            const lang = (m && m[1]) || "";
            const text = String(children || "").replace(/\n$/, "");
            if (lang.toLowerCase() === "mermaid") {
              return <Mermaid chart={text} />;
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

