# Sending WhatsApp messages to parents

The "Message parents" page (teacher portal) sends WhatsApp messages two
ways, and it's worth understanding the difference before you rely on either
one for a real cohort of students.

## What ships by default: click-to-chat links

Every "Attendance", "Homework", and "Send" button on that page is a
`wa.me` link — WhatsApp's own free deep-link format:

```
https://wa.me/<countrycode><number>?text=<url-encoded message>
```

Clicking it opens WhatsApp Web (on desktop) or the WhatsApp app (on
mobile) with the message already typed into the chat box. The teacher
still has to tap **Send** inside WhatsApp themselves.

**Why this is the default:**
- Needs no Meta/WhatsApp Business account, no API key, no approval wait
- Works the moment you run the app — nothing to configure
- Free, with no per-message cost

**Its one real limitation:** it's "one click per message," not silent,
unattended automation. A teacher messaging 30 parents taps 30 buttons (each
opens pre-filled — still much faster than typing each one from scratch, and
every send is logged in `parent_message_log` for a record).

Every generated message already includes a signature line identifying the
teacher and "ITM GIDA, Gorakhpur" — see `build_parent_message()` and
`whatsapp_link()` in `app.py` if you want to change the wording.

## Upgrading to true automatic sending (no click required)

If you want the server itself to fire off messages — e.g. automatically
message every parent the moment a student's attendance drops below 75%,
with no teacher involved — you need the **WhatsApp Business Cloud API**,
which is Meta's official server-to-server messaging API. This requires:

1. A **Meta Business Account** (business.facebook.com) — verified, which
   can take a few days.
2. A **WhatsApp Business App** created in Meta's developer console
   (developers.facebook.com), with a phone number registered to it.
3. **Pre-approved message templates** for anything sent outside a live
   24-hour conversation window — WhatsApp requires this for business-
   initiated messages (like attendance/homework alerts) specifically to
   stop spam. Templates are submitted for review and approved in advance,
   typically within a day.
4. A permanent **access token** and your **Phone Number ID** from the
   developer console.

### Code change needed

Only one function changes — `whatsapp_link()` in `app.py` currently
returns a `wa.me` URL for the browser to open. Swap it for a direct API
call instead:

```python
import requests

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID")

def send_whatsapp_message(phone, template_name, params):
    """Sends a pre-approved template message directly — no click needed."""
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,   # must match an approved template name exactly
            "language": {"code": "en"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in params]
            }]
        }
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()
```

Then in the routes that currently build a `wa.me` link (in the
`/teacher/message-parents` view and `teacher_message_parents_custom`),
call `send_whatsapp_message(...)` directly instead of rendering a link —
the message goes out immediately, no browser tab involved.

### Making it actually automatic (not just click-free)

To trigger messages without a teacher opening the page at all — e.g. "text
every parent the moment their child is marked absent" — call
`send_whatsapp_message()` from inside the attendance-marking logic itself.
The natural hook is right after a record is created in `/scan` (student
self-scan) or `/teacher/failsafe/submit` in `app.py`: check the student's
running attendance percentage there, and if it just dropped below 75%,
fire the message immediately as part of that same request.

For scheduled checks instead (e.g. "every evening, message parents of
anyone under 75% that day"), you'd add a small scheduled job — the
simplest option is a cron job that runs a short Python script (using the
same `send_whatsapp_message()` helper) once a day; `APScheduler` is a
reasonable in-process alternative if you'd rather not rely on system cron.

### Costs and limits to know about

- WhatsApp Business API messages are **not free** past a certain volume —
  Meta charges per conversation once you're outside their free tier, and
  pricing varies by country and message category. Check Meta's current
  rates before committing to sending at scale.
- Template messages must stick closely to their approved wording — you can
  fill in variables (student name, percentage, date) but can't freely
  rewrite the template text without resubmitting it for approval.
- Numbers need to be in full international format (country code, no `+`,
  no leading zero) — the same format the app already stores
  `parent_phone` in, so no data migration is needed either way.
