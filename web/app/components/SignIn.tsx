"use client";

/**
 * Sign-in: paste the bearer token the service issued.
 *
 * Deliberately not a username and password. This service does not hold credentials — it
 * holds hashed tokens, and a real deployment replaces the whole store with the division's
 * directory. A login form with a password field would imply an account system that does
 * not exist here, which is a worse lie than asking for a token.
 */

import { useEffect, useRef, useState } from "react";
import { useRole } from "./RoleProvider";

export default function SignIn({ onClose }: { onClose: () => void }) {
  const { signIn, error } = useRole();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const ok = await signIn(value);
    setBusy(false);
    if (ok) onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[14vh]"
      style={{ background: "rgba(12,18,26,0.45)" }}
      onClick={onClose}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="card w-[min(460px,92vw)] p-5"
      >
        <div className="sig mb-1">Sign in</div>
        <p className="text-[12px] leading-relaxed mb-3" style={{ color: "var(--ink-2)" }}>
          The approval route needs a bearer token. The service prints one per role the
          first time it runs, and stores only their hashes.
        </p>

        <input
          ref={inputRef}
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Bearer token"
          aria-label="Bearer token"
          autoComplete="off"
          spellCheck={false}
          className="mono w-full rounded-[3px] border px-2.5 py-2 text-[12px] outline-none"
          style={{ borderColor: "var(--line-2)", background: "var(--surface-2)" }}
        />

        {error && (
          <div className="mt-2 text-[11.5px]" style={{ color: "var(--crit)" }}>
            {error}
          </div>
        )}

        <div className="mt-3 flex items-center gap-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-[3px] px-3 py-[6px] text-[12px] font-medium"
            style={{ background: "var(--chrome)", color: "#fff", opacity: busy ? 0.6 : 1 }}
          >
            {busy ? "Checking…" : "Sign in"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-[3px] border px-3 py-[6px] text-[12px]"
            style={{ borderColor: "var(--line-2)", color: "var(--ink-2)" }}
          >
            Cancel
          </button>
        </div>

        <div className="mt-3 pt-3 text-[11px] leading-relaxed"
          style={{ borderTop: "1px solid var(--line)", color: "var(--ink-3)" }}>
          Lost the tokens? Delete <span className="mono">out/identities.json</span> and
          restart <span className="mono">scripts/serve.py</span> to mint a fresh set.
          Browsing the plan needs no sign-in; only acting on the approval route does.
        </div>
      </form>
    </div>
  );
}
