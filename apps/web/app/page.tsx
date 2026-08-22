import { redirect } from "next/navigation";

import { getAuthSession } from "../lib/auth";

export const dynamic = "force-dynamic";

export default async function Home() {
  const authenticated = await getAuthSession();
  redirect(authenticated ? "/workspace" : "/login");
}
