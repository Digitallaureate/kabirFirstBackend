"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getMagicWordRequests,
  getServiceOrders,
  isTodayInKolkata,
  MagicWordRequest,
  ServiceOrder
} from "@/lib/api";
import { RequestsView } from "@/components/requests-view";
import { OrdersView } from "@/components/orders-view";

export function DashboardOverview() {
  const [requests, setRequests] = useState<MagicWordRequest[]>([]);
  const [orders, setOrders] = useState<ServiceOrder[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const [requestData, orderData] = await Promise.all([getMagicWordRequests(), getServiceOrders()]);
        if (!mounted) return;
        setRequests(requestData.items || []);
        setOrders(orderData.items || []);
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Unable to load dashboard");
      }
    }

    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const stats = useMemo(() => {
    return {
      requests: requests.length,
      inProgress: requests.filter((item) => item.status === "inProgress").length,
      orders: orders.length,
      completedToday: requests.filter((item) =>
        item.status === "completed" && isTodayInKolkata(item.completedAt || item.updated_at || item.updatedAt || item.matchedAt)
      ).length
    };
  }, [orders.length, requests]);

  return (
    <>
      <section className="hero">
        <div>
          <h1>Customer Support</h1>
          <p>Manage traveller requests and service orders</p>
        </div>
        <div className="mountains" aria-hidden="true" />
        <div className="quote">People behind every journey</div>
      </section>

      {error ? <div className="notice error">{error}</div> : null}

      <section className="stats">
        <StatCard tone="rose" label="New Requests" value={stats.requests} icon="REQ" />
        <StatCard tone="blue" label="In Progress" value={stats.inProgress} icon="RUN" />
        <StatCard tone="orange" label="Open Orders" value={stats.orders} icon="ORD" />
        <StatCard tone="green" label="Completed Today" value={stats.completedToday} icon="OK" />
      </section>

      <section className="contentGrid">
        <RequestsView initialItems={requests} />
        <OrdersView initialItems={orders} />
      </section>
    </>
  );
}

function StatCard({ tone, label, value, icon }: { tone: string; label: string; value: number; icon: string }) {
  return (
    <div className="statCard">
      <span className={`statIcon ${tone}`}>{icon}</span>
      <div>
        <strong>{value}</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}
