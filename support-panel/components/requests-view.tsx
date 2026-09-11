"use client";

import { useEffect, useState } from "react";
import {
  formatSupportDate,
  getMagicWordRequests,
  getTravellerName,
  MagicWordRequest
} from "@/lib/api";
import { StatusBadge } from "@/components/status-badge";

export function RequestsView({
  initialItems,
  standalone = false
}: {
  initialItems?: MagicWordRequest[];
  standalone?: boolean;
}) {
  const [items, setItems] = useState<MagicWordRequest[]>(initialItems || []);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialItems) {
      setItems(initialItems);
      return;
    }

    let mounted = true;
    async function load() {
      try {
        const data = await getMagicWordRequests();
        if (mounted) setItems(data.items || []);
      } catch (err) {
        if (mounted) setError(err instanceof Error ? err.message : "Unable to load requests");
      }
    }

    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [initialItems]);

  return (
    <section className={`panel ${standalone ? "panelFull" : ""}`}>
      <div className="panelHead">
        <div>
          <b>Request Queue</b>
          <small>Latest traveller requests requiring your attention</small>
        </div>
        <button type="button" onClick={() => getMagicWordRequests().then((data) => setItems(data.items || []))}>
          Refresh
        </button>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      <div className="list">
        {items.length === 0 ? <div className="empty">No magic word requests found</div> : null}
        {items.map((item) => {
          const name = getTravellerName(item);
          const service = item.service_name || item.typeOfService || item.magicWord || "Travel Support";
          const message = item.userMessage || item.message || item.location || "Latest request update";

          return (
            <article className="requestRow" key={item.id}>
              <span className="person">{getInitials(name)}</span>
              <span>
                <b>{name}</b>
                <small>{message}</small>
              </span>
              <span className="rowMeta">{service}</span>
              <span className="rowTime">{formatSupportDate(item.matchedAt || item.created_at || item.updated_at)}</span>
              <StatusBadge status={item.status} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function getInitials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part.charAt(0).toUpperCase()).join("") || "T";
}
