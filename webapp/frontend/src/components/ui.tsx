import { useEffect, useRef } from "react";
import { motion, useReducedMotion } from "motion/react";
import { BookOpen, CircleAlert, X } from "lucide-react";
import { labelStatus } from "../api";

export function Status({ value }: { value?: string }) {
  return (
    <span className={`status status-${value || "empty"}`}>
      <span />
      {labelStatus(value)}
    </span>
  );
}

export function Empty({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <BookOpen size={32} />
      <h2>{title}</h2>
      <p>{description}</p>
      {children}
    </div>
  );
}

export function ErrorMessage({ error }: { error: string }) {
  return (
    <div className="inline-error" role="alert">
      <CircleAlert size={16} />
      <span>{error}</span>
    </div>
  );
}

export function Drawer({
  title,
  eyebrow,
  onClose,
  children,
}: {
  title: string;
  eyebrow: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      document.body.style.overflow = originalOverflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const fields = [
          ...(dialogRef.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex="0"]',
          ) ?? []),
        ].filter((element) => element.offsetParent !== null);
        const first = fields[0];
        const last = fields.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="drawer-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <motion.section
        ref={dialogRef}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        initial={{ x: reduced ? 0 : 35, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: reduced ? 0 : 0.18 }}
      >
        <header>
          <div>
            <div className="eyebrow">{eyebrow}</div>
            <h2>{title}</h2>
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="关闭面板"
          >
            <X size={20} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </motion.section>
    </div>
  );
}
