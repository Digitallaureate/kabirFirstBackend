# Customer Support Template Partials

`customer_support.html` is the small Jinja shell that includes these files.

- `_styles.html`: all page CSS, including the Traviz dashboard styles.
- `_dashboard.html`: small dashboard coordinator that includes the dashboard partials.
- `dashboard/_sidebar.html`: left sidebar, logged-in agent details, sound toggle, and logout.
- `dashboard/_topbar.html`: dashboard search bar.
- `dashboard/_overview.html`: dashboard overview hero, stats, and user summary area.
- `dashboard/_requests_panel.html`: request queue panel markup.
- `dashboard/_orders_panel.html`: service-order panel markup.
- `_magic_word_detail.html`: magic-word request detail screen and chat/reply UI.
- `_modals.html`: service request and completion reason modals.
- `_scripts.html`: script coordinator that includes the JavaScript partials in order.
- `scripts/_state.html`: shared variables, API base, logout, and sound notification.
- `scripts/_dashboard.html`: dashboard tab switching and user search.
- `scripts/_requests.html`: request list loading/rendering and request-detail opening.
- `scripts/_request_detail.html`: magic-word detail, chat, service request modal, and request status actions.
- `scripts/_service_orders.html`: service-order list/detail, vendor assignment, order status, and order chat.
- `scripts/_init.html`: initial dashboard data loading.
- `_service_order_detail.html`: service order detail screen, vendor assignment UI, and order chat panel.
