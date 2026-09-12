"use client";

/**
 * Who you are signed in as.
 *
 * This used to be a role *selector* — the browser picked a capacity and the service
 * believed it. It is now a session: you present a bearer token, the service resolves it
 * to a name and a role, and this holds what came back. The client cannot choose its own
 * authority any more, and the dropdown that implied it could is gone.
 *
 * The token lives in sessionStorage rather than localStorage, so closing the tab ends
 * the session. That is the right default for a control-room screen someone else will sit
 * at next.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

const TOKEN_KEY = "tracksen.token";

export interface Session {
  name: string;
  role: string;
}

interface Ctx {
  session: Session | null;
  token: string | null;
  /** Null while the stored token is being checked on first load. */
  checking: boolean;
  error: string | null;
  signIn: (token: string) => Promise<boolean>;
  signOut: () => void;
}

const RoleCtx = createContext<Ctx | null>(null);

export function useRole(): Ctx {
  const c = useContext(RoleCtx);
  if (!c) throw new Error("useRole must be used inside RoleProvider");
  return c;
}

function readStoredToken(): string | null {
  // sessionStorage throws outright in some embedded contexts rather than returning
  // null, and a sign-in screen that crashes is worse than one that asks again.
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export default function RoleProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** Ask the service who a token belongs to. The answer is not ours to decide. */
  const identify = useCallback(async (candidate: string): Promise<Session | null> => {
    const r = await fetch(`${API_BASE}/api/me`, {
      headers: { Authorization: `Bearer ${candidate}` },
    });
    if (!r.ok) return null;
    return (await r.json()) as Session;
  }, []);

  useEffect(() => {
    const stored = readStoredToken();
    if (!stored) {
      setChecking(false);
      return;
    }
    identify(stored)
      .then((who) => {
        if (who) {
          setSession(who);
          setToken(stored);
        } else {
          // The token was revoked or the identity file was regenerated. Drop it rather
          // than leaving a dead credential to fail on the next action.
          try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* not available */ }
        }
      })
      .catch(() => { /* service down; sign-in can be retried */ })
      .finally(() => setChecking(false));
  }, [identify]);

  const signIn = useCallback(async (candidate: string): Promise<boolean> => {
    setError(null);
    const trimmed = candidate.trim();
    if (!trimmed) {
      setError("Paste the bearer token the service printed on first run.");
      return false;
    }
    try {
      const who = await identify(trimmed);
      if (!who) {
        setError("That token was not recognised.");
        return false;
      }
      setSession(who);
      setToken(trimmed);
      try { sessionStorage.setItem(TOKEN_KEY, trimmed); } catch { /* not available */ }
      return true;
    } catch {
      setError("Could not reach the service. Is scripts/serve.py running?");
      return false;
    }
  }, [identify]);

  const signOut = useCallback(() => {
    setSession(null);
    setToken(null);
    setError(null);
    try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* not available */ }
  }, []);

  return (
    <RoleCtx.Provider value={{ session, token, checking, error, signIn, signOut }}>
      {children}
    </RoleCtx.Provider>
  );
}
