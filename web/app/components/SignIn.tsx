"use client";

/**
 * Sign in with a username and a password.
 *
 * This used to ask for a bearer token, on the reasoning that a password field would imply
 * an account system that did not exist — which was the right call at the time and the
 * wrong thing to leave standing. There are accounts now: per person rather than per role,
 * with passwords the service stores only as scrypt derivations, and sessions that expire
 * and can be revoked.
 *
 * The form has two steps because the first one can demand the second. Every account the
 * service mints on first run is flagged must-change-password, so the minted credential
 * cannot quietly become the permanent one.
 */

import { useEffect, useRef, useState } from "react";
import { useRole } from "./RoleProvider";

type Step = "credentials" | "change-password";

export default function SignIn({ onClose }: { onClose: () => void }) {
  const { signIn, error, session, changePassword } = useRole();
  const [step, setStep] = useState<Step>("credentials");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [nextPassword, setNextPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstField.current?.focus();
  }, [step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Escape cannot dismiss a forced password change: the session is live, so closing
      // the dialog would leave someone signed in on a credential they were told to replace.
      if (e.key === "Escape" && step === "credentials") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, step]);

  const submitCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setLocalError(null);
    const ok = await signIn(username, password);
    setBusy(false);
    if (!ok) return;
    // signIn has populated the session; if it is flagged, the dialog stays open.
    setStep("change-password");
  };

  // Signed in and nothing outstanding — close.
  useEffect(() => {
    if (step === "change-password" && session && !session.mustChangePassword) onClose();
  }, [step, session, onClose]);

  const submitNewPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (nextPassword !== confirm) {
      setLocalError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    const refusal = await changePassword(password, nextPassword);
    setBusy(false);
    if (refusal) {
      setLocalError(refusal);
      return;
    }
    onClose();
  };

  const shown = localError ?? error;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[14vh]"
      style={{ background: "rgba(12,18,26,0.45)" }}
      onClick={step === "credentials" ? onClose : undefined}
    >
      <form
        onSubmit={step === "credentials" ? submitCredentials : submitNewPassword}
        onClick={(e) => e.stopPropagation()}
        className="card w-[min(460px,92vw)] p-5"
      >
        {step === "credentials" ? (
          <>
            <div className="sig mb-1">Sign in</div>
            <p className="text-[12px] leading-relaxed mb-3" style={{ color: "var(--ink-2)" }}>
              The approval route needs an account. The service creates one per role the
              first time it runs and prints the passwords once, storing only their
              derivations.
            </p>

            <label className="sig block mb-1" htmlFor="signin-username">Username</label>
            <input
              id="signin-username"
              ref={firstField}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="drm"
              autoComplete="username"
              spellCheck={false}
              className="mono w-full rounded-[3px] border px-2.5 py-2 text-[12px] outline-none mb-2.5"
              style={{ borderColor: "var(--line-2)", background: "var(--surface-2)" }}
            />

            <label className="sig block mb-1" htmlFor="signin-password">Password</label>
            <input
              id="signin-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="mono w-full rounded-[3px] border px-2.5 py-2 text-[12px] outline-none"
              style={{ borderColor: "var(--line-2)", background: "var(--surface-2)" }}
            />
          </>
        ) : (
          <>
            <div className="sig mb-1">Choose a new password</div>
            <p className="text-[12px] leading-relaxed mb-3" style={{ color: "var(--ink-2)" }}>
              This account is still on the password the service minted for it. That one was
              printed to a terminal, so it is already in somebody&rsquo;s scrollback —
              replace it before acting on a plan. At least 12 characters.
            </p>

            <label className="sig block mb-1" htmlFor="new-password">New password</label>
            <input
              id="new-password"
              ref={firstField}
              type="password"
              value={nextPassword}
              onChange={(e) => setNextPassword(e.target.value)}
              autoComplete="new-password"
              className="mono w-full rounded-[3px] border px-2.5 py-2 text-[12px] outline-none mb-2.5"
              style={{ borderColor: "var(--line-2)", background: "var(--surface-2)" }}
            />

            <label className="sig block mb-1" htmlFor="confirm-password">Repeat it</label>
            <input
              id="confirm-password"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              className="mono w-full rounded-[3px] border px-2.5 py-2 text-[12px] outline-none"
              style={{ borderColor: "var(--line-2)", background: "var(--surface-2)" }}
            />
          </>
        )}

        {shown && (
          <div className="mt-2 text-[11.5px]" style={{ color: "var(--crit)" }}>
            {shown}
          </div>
        )}

        <div className="mt-3 flex items-center gap-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-[3px] px-3 py-[6px] text-[12px] font-medium"
            style={{ background: "var(--chrome)", color: "#fff", opacity: busy ? 0.6 : 1 }}
          >
            {busy
              ? "Working…"
              : step === "credentials"
                ? "Sign in"
                : "Set password"}
          </button>
          {step === "credentials" && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-[3px] border px-3 py-[6px] text-[12px]"
              style={{ borderColor: "var(--line-2)", color: "var(--ink-2)" }}
            >
              Cancel
            </button>
          )}
        </div>

        <div className="mt-3 pt-3 text-[11px] leading-relaxed"
          style={{ borderTop: "1px solid var(--line)", color: "var(--ink-3)" }}>
          {step === "credentials" ? (
            <>
              Lost the passwords? Delete <span className="mono">out/accounts.json</span> and
              restart <span className="mono">scripts/serve.py</span> to mint a fresh set.
              Browsing the plan needs no sign-in; only acting on the approval route does.
            </>
          ) : (
            <>
              Changing the password signs this account out of every other session.
            </>
          )}
        </div>
      </form>
    </div>
  );
}
