import { useEffect, useRef, useState } from "react";

// Real language logos via devicon (loaded in index.html). Native <select> can't render logos in
// its options, so this is a small custom dropdown.
const DEVICON: Record<string, string> = {
  python: "devicon-python-plain colored",
  typescript: "devicon-typescript-plain colored",
  javascript: "devicon-javascript-plain colored",
  java: "devicon-java-plain colored",
  go: "devicon-go-original-plain colored",
  rust: "devicon-rust-plain",
  bash: "devicon-bash-plain",
};
const iconClass = (l: string) => DEVICON[l] ?? "devicon-devicon-plain";

export function LanguagePicker(
  { value, options, onChange }: { value: string; options: string[]; onChange: (l: string) => void },
) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div className="lang-picker" ref={ref}>
      <button type="button" className="lang-trigger" aria-label="language" aria-haspopup="listbox"
        aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <i className={iconClass(value)} aria-hidden="true" />
        <span>{value}</span>
        <span className="caret">▾</span>
      </button>
      {open && (
        <ul className="lang-menu" role="listbox" aria-label="language options">
          {options.map((l) => (
            <li key={l} role="option" aria-selected={l === value}
              className={l === value ? "active" : ""}
              onClick={() => { onChange(l); setOpen(false); }}>
              <i className={iconClass(l)} aria-hidden="true" /> {l}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
