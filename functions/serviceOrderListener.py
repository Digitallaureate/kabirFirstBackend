from firebase_functions import firestore_fn
from firebase_admin import firestore, messaging
import logging


def _norm(s):
    return (s or "").strip().lower()


def _label(x):
    """field_values entries are sometimes {label, value} maps, sometimes plain strings."""
    if isinstance(x, dict):
        return x.get("label") or x.get("value") or ""
    return str(x) if x else ""


def _send_order_push(token: str, title: str, body: str, data: dict):
    """Single-token send, vendor 'alerts' channel (matches the vendor app)."""
    msg = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in (data or {}).items()},
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(channel_id="alerts"),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", content_available=True),
            ),
        ),
    )
    messaging.send(msg)


@firestore_fn.on_document_written(document="serviceJsonOrder/{orderId}")
def notify_vendors_on_open_order(event):
    """
    Push a new-order alert to every vendor whose serviceType matches the order's
    service_id, whenever the order JUST becomes 'booked' (newly created booked, or
    re-opened after a vendor cancel). Tokens live as an array on the vendor doc:
    vendor/{username}.fcmTokens
    """
    try:
        change = event.data
        after_snap = getattr(change, "after", None)
        before_snap = getattr(change, "before", None)

        after = after_snap.to_dict() if (after_snap and after_snap.exists) else None
        before = before_snap.to_dict() if (before_snap and before_snap.exists) else None

        if after is None:  # deleted
            return

        new_status = _norm(after.get("booking_status"))
        old_status = _norm(before.get("booking_status")) if before else None

        # Fire ONLY when it just became 'booked'. Skips booked->alloted, OTP
        # updates, completions, etc. (no spam).
        if new_status != "booked" or old_status == "booked":
            return

        service_id = (after.get("service_id") or "").strip()
        if not service_id:
            logging.warning("⚠️ Order has no service_id; skipping push")
            return

        order_id = after.get("order_id") or event.params["orderId"]
        service_name = after.get("service_name") or service_id
        fv = after.get("field_values") or {}

        monument = _label(fv.get("monument_id"))
        date = fv.get("travel_date") or fv.get("start_date") or ""
        time_ = fv.get("time_slot") or _label(fv.get("booking_mode")) or ""
        body = " • ".join([p for p in [monument, date, time_] if p]) or "New order available"
        title = f"New {service_name} order"

        data_payload = {
            "type": "new_order",
            "order_id": str(order_id),
            "service_id": service_id,
            "route": "/home",
        }

        db = firestore.client()
        vendors = db.collection("vendor").where("serviceType", "==", service_id).stream()

        sent = 0
        vendor_count = 0
        for vdoc in vendors:
            vendor_count += 1
            tokens = (vdoc.to_dict() or {}).get("fcmTokens") or []
            for token in tokens:
                if not token:
                    continue
                try:
                    _send_order_push(token, title, body, data_payload)
                    sent += 1
                except messaging.UnregisteredError:
                    # Stale token — prune it from the vendor doc.
                    try:
                        vdoc.reference.update(
                            {"fcmTokens": firestore.ArrayRemove([token])}
                        )
                        logging.info(f"🧹 Pruned dead token for vendor {vdoc.id}")
                    except Exception as prune_err:
                        logging.warning(f"prune failed for {vdoc.id}: {prune_err}")
                except Exception as send_err:
                    logging.warning(f"❌ push failed for {vdoc.id}: {send_err}")

        logging.info(
            f"📣 open-order push: order={order_id} service={service_id} "
            f"vendors={vendor_count} sent={sent}"
        )

    except Exception as e:
        logging.exception(f"❌ notify_vendors_on_open_order error: {e}")
