import React from "react";

export default function TabBar({ tabs, active, onChange }) {
  return (
    <div className="tabBar">
      {tabs.map((t) => (
        <button
          key={t.id}
          className={t.id === active ? "tab tabActive" : "tab"}
          onClick={() => onChange(t.id)}
          type="button"
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

