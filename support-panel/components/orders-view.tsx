"use client";

import { useEffect, useState } from "react";
import {
  formatSupportDate,
  getOrderTravellerName,
  getServiceOrders,
  ServiceOrder
} from "@/lib/api";
import { StatusBadge } from "@/components/status-badge";

export function OrdersView({
  initialItems,
  standalone = false
}: {
  initialItems?: ServiceOrder[];
  standalone?: boolean;
}) {
  const [items, setItems] = useState<ServiceOrder[]>(initialItems || []);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialItems) {
      setItems(initialItems);
      return;
    }

    let mounted = true;
    async function load() {
      try {
        const data = await getServiceOrders();
        if (mounted) setItems(data.items || []);
      } catch (err) {
        if (mounted) setError(err instanceof Error ? err.message : "Unable to load service orders");
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
          <b>Recent Service Orders</b>
          <small>Latest service orders and booking status</small>
        </div>
        <button type="button" onClick={() => getServiceOrders().then((data) => setItems(data.items || []))}>
          Refresh
        </button>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      <div className="list">
        {items.length === 0 ? <div className="empty">No booked service orders found</div> : null}
        {items.map((item) => {
          const title = item.service_name || "Order";
          const monument = item.field_values?.monument_id?.label || item.monument_name || "Destination";
          const date = formatSupportDate(item.field_values?.travel_date);

          return (
            <article className="orderRow" key={item.id}>
              <span className="thumb">{getOrderThumb(title)}</span>
              <span>
                <b>{title}</b>
                <small>{getOrderTravellerName(item)}</small>
              </span>
              <span className="rowMeta">{date !== "N/A" ? date : monument}</span>
              <StatusBadge status={item.booking_status || "booked"} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function getOrderThumb(title: string) {
  const text = title.toLowerCase();
  if (text.includes("cab") || text.includes("auto") || text.includes("traveller") || text.includes("tempo")) return "CAR";
  if (text.includes("guide") || text.includes("tour")) return "MON";
  if (text.includes("airport") || text.includes("transfer")) return "AIR";
  if (text.includes("hotel")) return "HOT";
  if (text.includes("photo")) return "CAM";
  return "ORD";
}
