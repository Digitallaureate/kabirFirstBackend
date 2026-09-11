export function StatusBadge({ status }: { status?: string }) {
  const value = status || "new";
  const className =
    value === "requested"
      ? "badge warning"
      : value === "inProgress"
        ? "badge primary"
        : value === "completed"
          ? "badge success"
          : "badge neutral";

  return <span className={className}>{value}</span>;
}
