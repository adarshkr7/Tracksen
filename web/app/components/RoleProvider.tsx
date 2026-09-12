"use client";

/**
 * The capacity a request is made in.
 *
 * This is NOT authentication. It selects which role the browser claims when calling the
 * approval route; the backend decides what that role may actually do and refuses the
 * rest. A real deployment binds `_actor()` in the service to the divisional directory,
 * at which point this selector becomes a display of who you already are.
 */

import { createContext, useContext, useState } from "react";

interface Ctx {
  actor: string;
  role: string;
  setActor: (v: string) => void;
  setRole: (v: string) => void;
}

const RoleCtx = createContext<Ctx | null>(null);

export function useRole(): Ctx {
  const c = useContext(RoleCtx);
  if (!c) throw new Error("useRole must be used inside RoleProvider");
  return c;
}

export default function RoleProvider({ children }: { children: React.ReactNode }) {
  const [actor, setActor] = useState("V. Kulkarni");
  const [role, setRole] = useState("DRM");
  return (
    <RoleCtx.Provider value={{ actor, role, setActor, setRole }}>
      {children}
    </RoleCtx.Provider>
  );
}
