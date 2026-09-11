export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/support";

export type RequestStatus = "requested" | "inProgress" | "completed" | string;

export type MagicWordRequest = {
  id: string;
  status?: RequestStatus;
  matchedAt?: string;
  created_at?: string;
  updated_at?: string;
  updatedAt?: string;
  completedAt?: string;
  messageId?: string;
  magicWord?: string;
  userMessage?: string;
  message?: string;
  location?: string;
  service_name?: string;
  typeOfService?: string;
  userName?: string;
  traveller_name?: string;
  customer_name?: string;
  name?: string;
  user?: {
    firstName?: string;
    lastName?: string;
    name?: string;
  };
};

export type ServiceOrder = {
  id: string;
  service_name?: string;
  monument_name?: string;
  booking_status?: string;
  user_name?: string;
  traveller_name?: string;
  customer_name?: string;
  user?: {
    name?: string;
  };
  field_values?: {
    travel_date?: string;
    monument_id?: {
      label?: string;
    };
  };
};

type ListResponse<T> = {
  found?: boolean;
  count?: number;
  items?: T[];
};

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function getMagicWordRequests(userId?: string) {
  const suffix = userId ? `?userId=${encodeURIComponent(userId)}` : "";
  return fetchJson<ListResponse<MagicWordRequest>>(`/api/magic-words${suffix}`);
}

export async function getServiceOrders() {
  return fetchJson<ListResponse<ServiceOrder>>("/api/service-orders");
}

export function getTravellerName(item: MagicWordRequest) {
  const user = item.user || {};
  const fullName = `${user.firstName || ""} ${user.lastName || ""}`.trim();
  return item.userName || item.traveller_name || item.customer_name || item.name || user.name || fullName || "Traveller";
}

export function getOrderTravellerName(item: ServiceOrder) {
  return item.user_name || item.traveller_name || item.customer_name || item.user?.name || "Traveller";
}

export function formatSupportDate(value?: string) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true
  });
}

export function isTodayInKolkata(value?: string) {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const itemDay = date.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  return today === itemDay;
}
