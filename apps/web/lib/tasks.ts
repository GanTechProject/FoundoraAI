import { cookies } from "next/headers";

export const taskStatuses = [
  "draft",
  "planned",
  "queued",
  "running",
  "blocked",
  "waiting_approval",
  "completed",
  "failed",
  "cancelled",
] as const;

export type TaskStatus = (typeof taskStatuses)[number];

export interface TaskDependency {
  task_id: string;
  title: string;
  status: TaskStatus;
  satisfied: boolean;
}

export interface TaskEvent {
  id: string;
  event_type: "created" | "dependency_added" | "status_changed" | "retried";
  from_status: TaskStatus | null;
  to_status: TaskStatus | null;
  idempotency_key: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface FoundoraTask {
  id: string;
  business_id: string;
  goal_id: string | null;
  title: string;
  description: string | null;
  priority: number;
  owner_type: "unassigned" | "founder" | "agent";
  owner_agent_id: string | null;
  owner_agent_version_id: string | null;
  owner_agent_version: number | null;
  status: TaskStatus;
  due_at: string | null;
  max_retries: number;
  retry_count: number;
  last_error: string | null;
  dependencies: TaskDependency[];
  blocked_by: string[];
  events: TaskEvent[];
  created_at: string;
  updated_at: string;
}

export interface TaskDashboard {
  business_id: string;
  goals: Array<{
    id: string;
    title: string;
    status: "active" | "completed" | "cancelled";
    target_date: string | null;
  }>;
  agent_owners: Array<{
    agent_id: string;
    display_name: string;
    version: number;
  }>;
  tasks: FoundoraTask[];
}

function isTask(value: unknown): value is FoundoraTask {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<FoundoraTask>;
  return (
    typeof item.id === "string" &&
    typeof item.business_id === "string" &&
    typeof item.title === "string" &&
    typeof item.priority === "number" &&
    taskStatuses.includes(item.status as TaskStatus) &&
    Array.isArray(item.dependencies) &&
    Array.isArray(item.blocked_by) &&
    Array.isArray(item.events) &&
    typeof item.retry_count === "number" &&
    typeof item.max_retries === "number"
  );
}

function isDashboard(value: unknown): value is TaskDashboard {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<TaskDashboard>;
  return (
    typeof item.business_id === "string" &&
    Array.isArray(item.goals) &&
    Array.isArray(item.agent_owners) &&
    Array.isArray(item.tasks) &&
    item.tasks.every(isTask)
  );
}

async function taskFetch(path: string): Promise<unknown | null> {
  const store = await cookies();
  const session = store.get("id")?.value;
  if (!session) return null;
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}${path}`, {
      cache: "no-store",
      headers: { Cookie: `id=${session}` },
      signal: AbortSignal.timeout(5000),
    });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export async function getTaskDashboard(): Promise<TaskDashboard | null> {
  const value = await taskFetch("/tasks");
  return isDashboard(value) ? value : null;
}

export async function getTask(taskId: string): Promise<FoundoraTask | null> {
  if (!/^[0-9a-f-]{36}$/i.test(taskId)) return null;
  const value = await taskFetch(`/tasks/${encodeURIComponent(taskId)}`);
  return isTask(value) ? value : null;
}
