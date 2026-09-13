"use client";

/**
 * Who you are signed in as.
 *
 * Three versions of this have existed and the differences matter. It began as a role
 * *selector* — the browser picked a capacity and the service believed it. Then it became
 * a pasted bearer token, which was real authentication but per role, permanent, and
 * impossible to revoke. It is now a session: you sign in with a username and a password,
 * the service issues a token that expires, and this holds what came back.
 *
 * The client still cannot choose its own authority. What changed is that the thing it
 * holds can now be taken away — by signing out, by changing the password, by the absolute
 * lifetime running out, or by sitting idle at an unattended screen.
 *
 * The token lives in sessionStorage rather than localStorage, so closing the tab ends the
 * session in this browser as well as on the server. That is the right default for a
 * control-room screen someone else will sit at next.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";

const TOKEN_KEY = "tracksen.token";

/**
 * How often to ask the service whether this session is still good.
 *
 * The server enforces both clocks; this only makes the answer visible. Without it a
 * screen left open shows a signed-in DRM for hours after the session behind it lapsed,
 * and the first anyone learns of it is a 401 in the middle of sanctioning something.
 */
const RECHECK_MS = 60_000;

export interface Session {
  name: string;
  username: string;
  role: string;
  expiresAt: string | null;
  mustChangePassword: boolean;
}

interface Ctx {
  session: Session | null;
  token: string | null;
  /** Null while a stored token is being checked on first load. */
  checking: boolean;
  error: string | null;
  /** Set when a live session ended on the server rather than by the user. */
  endedReason: string | null;
  signIn: (username: string, password: string) => Promise<boolean>;
  signOut: () => void;
  changePassword: (current: string, next: string) => Promise<string | null>;
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

function store(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* not available; the session simply does not survive a reload */
  }
}

interface MeResponse {
  name: string;
  username: string;
  role: string;
  expires_at: string | null;
  must_change_password: boolean;
}

function toSession(me: MeResponse): Session {
  return {
    name: me.name,
    username: me.username,
    role: me.role,
    expiresAt: me.expires_at ?? null,
    mustChangePassword: Boolean(me.must_change_password),
  };
}

export default function RoleProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [endedReason, setEndedReason] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);

  tokenRef.current = token;

  /**
   * Ask the service who a token belongs to. Returns the session, or the reason it is no
   * longer one — "session idle for more than 60 minutes" reads very differently from
   * "session not recognised", and the user can act on the difference.
   */
  const identify = useCallback(
    async (candidate: string): Promise<{ who: Session | null; reason: string | null }> => {
      const r = await fetch(`${API_BASE}/api/me`, {
        headers: { Authorization: `Bearer ${candidate}` },
      });
      if (r.ok) return { who: toSession((await r.json()) as MeResponse), reason: null };
      let reason = "session is no longer valid";
      try {
        const body = await r.json();
        if (typeof body?.detail === "string") reason = body.detail;
      } catch {
        /* no body; the generic reason stands */
      }
      return { who: null, reason };
    },
    [],
  );

  const clear = useCallback((reason: string | null) => {
    setSession(null);
    setToken(null);
    store(null);
    setEndedReason(reason);
  }, []);

  // First load: is the token this tab is holding still good?
  useEffect(() => {
    const stored = readStoredToken();
    if (!stored) {
      setChecking(false);
      return;
    }
    identify(stored)
      .then(({ who, reason }) => {
        if (who) {
          setSession(who);
          setToken(stored);
        } else {
          // Expired, revoked, or the accounts file was regenerated. Drop it rather than
          // leaving a dead credential to fail on the next action.
          clear(reason);
        }
      })
      .catch(() => { /* service down; sign-in can be retried */ })
      .finally(() => setChecking(false));
  }, [identify, clear]);

  // Then keep asking, so an expiry shows up as a sign-out rather than as a failed action.
  useEffect(() => {
    if (!token) return;
    const id = setInterval(() => {
      const held = tokenRef.current;
      if (!held) return;
      identify(held)
        .then(({ who, reason }) => {
          if (who) setSession(who);
          else clear(reason);
        })
        .catch(() => { /* transient; the next tick tries again */ });
    }, RECHECK_MS);
    return () => clearInterval(id);
  }, [token, identify, clear]);

  const signIn = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      setError(null);
      setEndedReason(null);
      if (!username.trim() || !password) {
        setError("Enter your username and password.");
        return false;
      }
      try {
        const r = await fetch(`${API_BASE}/api/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username.trim(), password }),
        });
        if (!r.ok) {
          let detail = "Username or password not recognised.";
          try {
            const body = await r.json();
            if (typeof body?.detail === "string") detail = body.detail;
          } catch {
            /* no body; the generic message stands */
          }
          setError(detail);
          return false;
        }
        const body = await r.json();
        setToken(body.token);
        store(body.token);
        setSession(
          toSession({
            name: body.name,
            username: body.username,
            role: body.role,
            expires_at: body.expires_at,
            must_change_password: body.must_change_password,
          }),
        );
        return true;
      } catch {
        setError("Could not reach the service. Is scripts/serve.py running?");
        return false;
      }
    },
    [],
  );

  const signOut = useCallback(() => {
    const held = tokenRef.current;
    setError(null);
    // Told to the server as well as forgotten here. A client-side-only sign-out leaves a
    // live session behind that nothing will ever close, which is the failure this whole
    // change exists to remove.
    if (held) {
      fetch(`${API_BASE}/api/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${held}` },
      }).catch(() => { /* the session still expires on its own */ });
    }
    clear(null);
  }, [clear]);

  /** Returns null on success, or the reason it was refused. */
  const changePassword = useCallback(
    async (current: string, next: string): Promise<string | null> => {
      const held = tokenRef.current;
      if (!held) return "You are not signed in.";
      try {
        const r = await fetch(`${API_BASE}/api/password`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${held}`,
          },
          body: JSON.stringify({ current_password: current, new_password: next }),
        });
        if (!r.ok) {
          let detail = "That password was refused.";
          try {
            const body = await r.json();
            if (typeof body?.detail === "string") detail = body.detail;
          } catch {
            /* generic message stands */
          }
          return detail;
        }
        setSession((s) => (s ? { ...s, mustChangePassword: false } : s));
        return null;
      } catch {
        return "Could not reach the service.";
      }
    },
    [],
  );

  return (
    <RoleCtx.Provider
      value={{ session, token, checking, error, endedReason, signIn, signOut, changePassword }}
    >
      {children}
    </RoleCtx.Provider>
  );
}
