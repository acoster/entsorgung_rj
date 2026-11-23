# Entsorgung RJ (`ch.adaptit.entsorgungrj`) — API Notes

Technical documentation of the **Entsorgung RJ** (Rapperswil-Jona waste disposal calendar) backend API, derived from inspecting the Flutter app (`v1.4.2` Android APK + `v1.4.8` iOS/macOS app) and live API responses.

## Overview

- **App package:** `ch.adaptit.entsorgungrj` (Flutter + `dio` + `pretty_dio_logger`)
- **Transport:** Standard **HTTPS REST JSON API** (Laravel / Apache)
- **Base URL:** `https://wastedisposalschedule-be.adaptit.ch/api/v1/`
- **Rate limit:** `300` requests/minute (`X-RateLimit-Limit: 300`).
- **OpenAPI spec:** See [openapi.yaml](./openapi.yaml).

## Authentication & Registration (v1.4.8)

In `v1.4.2` (2023), the app authenticated with a single `Device-Token` header and sent `{"device_token": ...}` / `{"region_id": ...}` (snake_case).

In `v1.4.8`, the backend switched to **lowercase hyphenated** keys/headers and added an anonymous installation UUID (`anonymous-user-id`):

| Header / Field | Value |
|---|---|
| `anonymous-user-id` | Any client-generated UUID v4 (e.g. `3d83c7ea-7713-4672-99ee-c3ba7abb162c`) |
| `device-token` | FCM registration token in the mobile app, or any non-empty string (e.g. `cli-<uuid>`)—the backend does **not** validate it against Firebase |

### Required flow to fetch a district's calendar

1. **Register the client identity** (once per client UUID):
   ```http
   POST /api/v1/register-device
   Content-Type: application/json

   {
     "device-token": "cli-<uuid>",
     "anonymous-user-id": "<uuid>"
   }
   ```
2. **List available districts (Kreise):**
   ```http
   GET /api/v1/regions
   anonymous-user-id: <uuid>
   device-token: cli-<uuid>
   ```
   Returns `Kreis 1` (`id: 1`) through `Kreis 8` (`id: 8`).
3. **Bind the client identity to a district:**
   ```http
   POST /api/v1/set-region-preference
   Content-Type: application/json
   anonymous-user-id: <uuid>
   device-token: cli-<uuid>

   {
     "device-token": "cli-<uuid>",
     "anonymous-user-id": "<uuid>",
     "region-id": 2
   }
   ```
4. **Fetch the rubbish collection calendar** (returns a 60-day window starting today for the district bound to that `device-token`):
   ```http
   GET /api/v1/collection-schedule
   anonymous-user-id: <uuid>
   device-token: cli-<uuid>
   ```

> **Note:** District selection is stored server-side per `device-token`. If an unregistered `device-token` is passed to `GET /collection-schedule`, the server falls back to `region_id = 1` (`Kreis 1`).

## Endpoints Summary

| Method | Path | Auth Headers | Purpose |
|---|---|---|---|
| `POST` | `/register-device` | None | Register `device-token` + `anonymous-user-id` |
| `GET` | `/regions` | Required | List all 8 Rapperswil-Jona districts (`Kreis 1`–`Kreis 8`) |
| `POST` | `/set-region-preference` | Required | Set the active district (`region-id`) for a device |
| `GET` | `/collection-schedule` | Required | Fetch upcoming 60-day collection dates for the active district |
| `GET` | `/categories` | Required | List waste categories (`Karton`, `Kehricht`, `Grüngut`, `Metall`, `Papier`) with descriptions & icons |
| `GET` | `/self-disposals` | Required | List local drop-off / recycling centers (e.g. *Engelhölzli*) with coordinates & opening hours |
| `GET` | `/get-company-settings` | Required | Privacy URL, contact email, and official PDF calendar link |
| `GET` | `/get-preference` | Required | List categories and notification subscriptions for the device |
| `POST` | `/set-preference` | Required | Update notification category preferences (`category_ids`) |
