# Customer Service Panel Documentation

## Purpose

This document explains how the customer service panel works in the current implementation.
It is meant to help you understand the codebase, trace the flow end to end, and make future changes safely on your own.

The customer service panel is a Flask-based admin UI exposed through Firebase Functions. It supports:

- admin login
- viewing service orders
- opening a full order detail screen
- updating booking status
- assigning vendors
- viewing recent chat messages
- sending chat messages to users

## High-Level Architecture

The flow is:

1. Browser opens the customer service panel.
2. Firebase Function receives the HTTP request.
3. The request is forwarded to the Flask app.
4. Flask serves either:
   - an HTML page, or
   - a JSON API response
5. Frontend JavaScript calls backend APIs using `fetch(...)`.
6. Backend reads and writes Firestore data.
7. Backend normalizes Firestore data before sending it to the frontend.

In short:

`Frontend HTML/JS -> Flask routes -> Firestore`

## Main Files

### 1. Entry Point

File: [main.py](/abs/c:/python_project/initial_project/functions/main.py)

This is the Firebase Function entry layer.

Important points:

- `customerService_app` is the HTTP function used for this panel.
- It forwards incoming requests to the Flask app defined in `app.py`.
- Local emulator and deployed function requests both come through here.

If the panel URL opens but behavior is strange, always confirm that this wrapper is forwarding the request correctly.

### 2. Main Backend

File: [app.py](/abs/c:/python_project/initial_project/functions/app.py)

This is the core backend for the panel.

It handles:

- Flask app setup
- local/deployed path handling
- session-based login
- page routes
- service order APIs
- order detail APIs
- vendor assignment APIs
- booking status update APIs
- chat read/send APIs
- Firestore normalization helpers

This is the most important backend file for customer service.

### 3. Login Page

File: [index.html](/abs/c:/python_project/initial_project/functions/customerService/templates/index.html)

This is the admin login page.

Responsibilities:

- render username/password fields
- submit login request
- handle login success or failure
- redirect to the next screen after login

This page also contains frontend base-path handling so that it works in both:

- local emulator
- deployed Firebase Function URL

### 4. Customer Support Main Screen

File: [customer_support.html](/abs/c:/python_project/initial_project/functions/customerService/templates/customer_support.html)

This is the primary UI for the new customer service flow.

It contains:

- order list UI
- order detail screen
- dynamic field rendering
- status update UI
- vendor assignment UI
- chat history UI
- send-message UI
- JavaScript API calls

Most frontend behavior now lives in this file.

### 5. Dashboard

File: [dashboard.html](/abs/c:/python_project/initial_project/functions/customerService/templates/dashboard.html)

This is the higher-level dashboard or navigation page.
It is lighter than the customer support screen and is mainly useful for top-level panel navigation.

### 6. Older / Secondary Orders Page

File: [orders.html](/abs/c:/python_project/initial_project/functions/customerService/templates/orders.html)

This appears to be an older or secondary orders UI.
The main active service-order experience is currently centered in `customer_support.html`.

If you are changing the new implementation, start with:

- `customer_support.html`
- `app.py`

### 7. Service Request / Magic Word Logic

File: [magic_word_summary.py](/abs/c:/python_project/initial_project/functions/customerService/magic_word_summary.py)

This file contains logic related to older magic-word and service-request flows.

It is still relevant because:

- some chat-related patterns originated here
- some order creation logic still depends on this area
- some legacy data assumptions can still affect the panel

However, for the current service order panel, it is not the first place to edit unless you are changing upstream order creation behavior.

## URL and Entry Flow

### Local URL

When running in the local Firebase emulator, the panel typically starts from:

`http://127.0.0.1:5001/ecostory-b31b6/us-central1/customerService_app/login`

### Deployed URL

In deployed mode, the function path changes, but the same Flask routes are used internally.

### Important Note About Base Path

Because the local emulator path includes:

`/ecostory-b31b6/us-central1/customerService_app`

the frontend cannot assume root-relative URLs like `/login` or `/api/...`.

To solve this, the frontend uses a helper such as `getBasePath()` to compute the correct base URL for both environments.

This is one of the most important pieces of the panel because many local issues come from incorrect path construction.

## Main Backend Responsibilities in `app.py`

You can think of `app.py` in these sections.

### A. App Setup

This area handles:

- Flask initialization
- session management
- middleware for local/deployed path compatibility

Relevant idea:

- the app needs to work even when requests include extra emulator prefixes before the actual route

### B. Page Routes

These routes render HTML templates.

Examples include:

- `/login`
- `/dashboard`
- `/customer-support`

If a page shows `Not Found`, start here first.

### C. API Routes

These routes return JSON and are called from frontend JavaScript.

Important categories:

- service order list
- service order detail
- status updates
- vendor assignment
- chat loading
- chat sending
- image upload

If a button click or screen load is broken, the issue is often in an API route.

### D. Helper Functions

These help translate Firestore data into a stable frontend structure.

Examples:

- `_service_order_value(...)`
- `_service_order_number(...)`
- `_humanize_field_key(...)`
- `_normalize_service_json_order(...)`
- `_get_latest_chat_for_user(...)`
- `_create_customer_service_chat_message(...)`

These helpers are very important because Firestore order documents are not always identical.

## Service Order Data Flow

The new implementation now uses the `serviceJsonOrder` collection as the main order source.

### Why Normalization Is Needed

The raw documents in `serviceJsonOrder` can vary:

- field names can differ
- nested values can vary
- `field_values` content is dynamic
- not every order has the same keys

Because of that, the backend should normalize the document before sending it to the frontend.

### Current Pattern

1. Read raw document from `serviceJsonOrder`.
2. Extract important values safely.
3. Convert them into a predictable shape.
4. Return normalized JSON to the frontend.

This keeps the frontend simpler and safer.

### Important Design Principle

Keep the frontend display-oriented and let the backend handle messy data translation.

That means:

- if Firestore schema changes, prefer fixing backend normalization first
- do not push schema complexity into HTML/JS unless needed

## Order List Flow

The order list shown in the customer support screen works like this:

1. `customer_support.html` loads.
2. JavaScript computes the correct base path.
3. Frontend calls the service order list API.
4. Backend reads `serviceJsonOrder`.
5. Backend normalizes each order document.
6. Frontend renders order cards or rows.

Displayed list data usually includes:

- traveler name
- phone
- service name
- monument
- date
- time slot
- booking status
- payment status

If the list is empty, debug:

- frontend `fetch(...)`
- backend list route
- Firestore collection name
- normalization logic

## Order Detail Flow

When the user clicks an order from the list:

1. Frontend calls the order detail API using the order ID.
2. Backend loads the full order from Firestore.
3. Backend normalizes the order detail.
4. Backend also tries to attach the latest chat for that user.
5. Frontend fills the order detail screen using `sod-*` elements.

Examples of detail fields:

- `sod-orderId`
- `sod-travelerName`
- `sod-travelerPhone`
- `sod-monument`
- `sod-serviceType`
- `sod-dateOfService`
- `sod-timeSlot`
- `sod-statusBadge`
- `sod-userId`
- `sod-userEmail`
- `sod-currentVendor`
- `sod-createdAt`
- `sod-updatedAt`

The order detail view is now a dedicated full-screen section inside `customer_support.html`, not just a modal popup.

## Dynamic Field Handling

One important requirement in the new flow is that order fields are dynamic.

This means:

- not every order contains the same `field_values`
- some services may include custom fields
- different services may produce different payload shapes

### Current Strategy

Backend:

- inspects dynamic data
- converts raw field keys into safer display data
- sends a display-friendly structure to the frontend

Frontend:

- uses a dynamic rendering function to display whatever fields are present
- does not hardcode all possible service-specific fields

This is the correct direction for this panel because the order schema is not fixed.

## Single-Service Assumption

Previously, parts of the system assumed an order might include a list of services.

Now the new requirement is:

- one order should be treated as one service

This affects:

- order normalization
- service request creation
- detail rendering
- field naming expectations

### Practical Effect

Instead of showing or processing multiple services for one order, the system now expects one primary service to be displayed and managed.

If old data still contains lists, backend logic should safely reduce it to the primary service for display and operational purposes.

## Chat Flow in Order Detail

The order detail page now supports chat display and reply handling similar to the magic-word detail flow.

### What Happens

When an order is opened:

1. Backend tries to find the latest chat for the user linked to the order.
2. The detail API returns that chat metadata.
3. Frontend stores the chat ID.
4. Frontend loads the latest messages.
5. Frontend starts polling periodically.
6. Support can send a new message from the same screen.

### Chat Display

The order detail screen now includes:

- chat ID display
- recent messages area
- send message textarea
- send button

### Chat Send API

The message send flow uses a generic route pattern:

`/api/chats/<chat_id>/send-message`

This allows the customer service panel to send support messages directly into the existing chat stream.

### Important Frontend State

The frontend keeps track of the currently active order chat using a variable like:

`currentServiceOrderChatId`

If chat is not loading correctly, this is one of the first things to inspect.

## Vendor Assignment Flow

From the order detail screen, support can assign or change a vendor.

Typical flow:

1. Open order detail.
2. Load current vendor information.
3. Load available vendor choices.
4. Select a vendor.
5. Optionally enter vendor price.
6. Submit assignment request.
7. Backend updates Firestore.
8. Frontend refreshes displayed vendor details.

If vendor assignment fails, check:

- selected vendor ID
- request payload
- backend update route
- Firestore write permissions or field mapping

## Booking Status Update Flow

The detail screen also supports booking status changes.

Typical statuses include:

- `booked`
- `confirmed`
- `in_progress`
- `completed`
- `cancelled`

Flow:

1. User selects a new status.
2. Frontend sends API request.
3. Backend updates the Firestore document.
4. Frontend updates the badge and detail state.

If status updates are not reflected, inspect both:

- API response
- Firestore document after update

## Login Flow

The login page in `index.html` sends credentials to the backend login route.

Backend responsibilities:

- parse incoming request body
- validate username/password
- set session or authenticated state
- return JSON success/failure response

One previous local issue happened because emulator forwarding and request-body handling did not match deployed behavior.
That is why request parsing and WSGI forwarding logic were adjusted in the current implementation.

## Local Emulator vs Deployed Behavior

One major source of confusion in this panel has been the difference between:

- deployed Firebase Function behavior
- local Firebase emulator behavior

### Common Differences

- URL includes extra prefix in local emulator
- request body forwarding can behave differently
- direct root-relative frontend fetch paths may fail locally
- middleware/path stripping is more important locally

### Practical Rule

If something works in deploy but not locally, check:

1. base path construction
2. request forwarding in `main.py`
3. route stripping/middleware in `app.py`
4. request body parsing for POST routes

## Firestore Areas Involved

The main current Firestore area for service order display is:

- `serviceJsonOrder`

Other related Firestore areas can include:

- chat documents/messages
- vendor data
- legacy service request or magic-word data

When debugging, always identify exactly which collection the current screen is reading from.

Do not assume older customer service flows still use the same collection as the new order screen.

## Recommended Development Workflow

When making changes, use this pattern.

### If You Are Changing UI

Start in:

- [customer_support.html](/abs/c:/python_project/initial_project/functions/customerService/templates/customer_support.html)

Examples:

- add a new field
- change layout
- rename labels
- show extra order metadata
- add a new button

### If You Are Changing Data or API Behavior

Start in:

- [app.py](/abs/c:/python_project/initial_project/functions/app.py)

Examples:

- change query logic
- fix JSON response structure
- add a new route
- change how order detail is built
- adjust login behavior

### If Firestore Shape Is Inconsistent

Start in:

- normalization helpers in `app.py`

Examples:

- field is sometimes nested and sometimes flat
- numeric value may be string in some docs
- `field_values` differs per service
- one order is missing expected keys

### If You Are Changing Upstream Order Creation

Start in:

- [magic_word_summary.py](/abs/c:/python_project/initial_project/functions/customerService/magic_word_summary.py)

Examples:

- how service requests are created
- how service order documents are produced
- how single-service assumptions are enforced earlier in the flow

## Debugging Checklist

### 1. Page Shows `Not Found`

Check:

- correct local URL
- page route in `app.py`
- emulator path forwarding in `main.py`
- middleware/path handling in `app.py`

### 2. Login Fails or Hangs

Check:

- frontend `fetch('/login')` path construction
- backend login route
- request body parsing
- local forwarding logic

### 3. Orders Do Not Load

Check:

- frontend service order fetch call
- backend service order API route
- Firestore query result
- normalization output

### 4. Order Detail Opens but Data Is Missing

Check:

- detail API response payload
- mapping to `sod-*` elements
- dynamic fields renderer
- whether the field exists in raw Firestore document

### 5. Chat Is Not Showing

Check:

- detail API returns `chat`
- frontend stored `currentServiceOrderChatId`
- chat messages API response
- polling function execution

### 6. Send Message Fails

Check:

- current chat ID exists
- request payload contains message
- backend send-message route
- Firestore write success

### 7. Vendor Assignment Fails

Check:

- selected vendor value
- vendor price handling
- backend assignment route
- Firestore write result

### 8. Status Update Fails

Check:

- selected status value
- backend update route
- Firestore document update
- frontend refresh logic

## Mental Model to Keep

The easiest way to think about this system is:

- `HTML/JS` is responsible for display and user interaction
- `Flask routes` are responsible for application logic
- `Firestore` is responsible for persistence
- `normalization helpers` are responsible for translating raw data into UI-safe data

If you keep that mental model, debugging becomes much easier.

## Suggested Learning Order

If you want to get comfortable working on this panel independently, read the code in this order:

1. [main.py](/abs/c:/python_project/initial_project/functions/main.py)
2. [app.py](/abs/c:/python_project/initial_project/functions/app.py)
3. [customer_support.html](/abs/c:/python_project/initial_project/functions/customerService/templates/customer_support.html)
4. [index.html](/abs/c:/python_project/initial_project/functions/customerService/templates/index.html)
5. [dashboard.html](/abs/c:/python_project/initial_project/functions/customerService/templates/dashboard.html)
6. [magic_word_summary.py](/abs/c:/python_project/initial_project/functions/customerService/magic_word_summary.py)

## Safe Change Strategy

Whenever you make a change, follow this sequence:

1. Identify the exact screen or button involved.
2. Find the corresponding frontend function in `customer_support.html`.
3. Identify which API route that function calls.
4. Inspect the backend route in `app.py`.
5. Confirm which Firestore collection or document is being used.
6. If data shape is inconsistent, fix it in backend normalization.
7. Re-test in the local emulator with the correct function path.

This approach will help you avoid making random edits across multiple files.

## Summary

The new customer service implementation is centered around:

- `customerService_app` as the function entry
- `app.py` as the Flask backend
- `customer_support.html` as the main frontend
- `serviceJsonOrder` as the main order data source
- backend normalization for dynamic fields
- single-service handling
- integrated order-detail chat support

If you are unsure where to start on any issue, first decide whether it is:

- a UI problem
- an API problem
- a Firestore schema problem
- an upstream order creation problem

That one decision usually tells you which file to open first.
