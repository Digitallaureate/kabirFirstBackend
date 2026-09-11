# Customer Support Template Partials

`customer_support.html` is the small Jinja shell that includes these files.

- `_styles.html`: all page CSS, including the Traviz dashboard styles.
- `_dashboard.html`: small dashboard coordinator that includes the dashboard partials.
- `dashboard/_sidebar.html`: left sidebar nav (Dashboard/Requests/Service Orders/Users), logged-in agent details, sound toggle, and logout.
- `dashboard/_overview.html`: dashboard overview hero (with the stats reporting-range control) and stat cards.
- `dashboard/_requests_panel.html`: request queue panel markup.
- `dashboard/_orders_panel.html`: service-order panel markup.
- `dashboard/_users_panel.html`: Users tab -- traveller search (name/email/mobile) and the user detail card, with "View User Requests"/"View User Orders" actions that jump to the respective tab filtered by that user.
- `_magic_word_detail.html`: magic-word request detail screen and chat/reply UI.
- `_modals.html`: service request and completion reason modals.
- `_scripts.html`: script coordinator that includes the JavaScript partials in order.
- `scripts/_state.html`: shared variables, API base, logout, and sound notification.
- `scripts/_dashboard.html`: dashboard tab switching, stats reporting-range control, and the Users tab's search/selection flow.
- `scripts/_requests.html`: request list loading/rendering and request-detail opening.
- `scripts/_request_detail.html`: magic-word detail, chat, service request modal, and request status actions.
- `scripts/_service_orders.html`: service-order list/detail, vendor assignment, order status, and order chat.
- `scripts/_init.html`: initial dashboard data loading.
- `_service_order_detail.html`: service order detail screen, vendor assignment UI, and order chat panel.
