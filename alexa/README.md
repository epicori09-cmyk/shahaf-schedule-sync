# My School Schedule Alexa Skill

This is the Alexa-hosted Python skill for the Shahaf schedule project.

## First-time setup

1. In the Alexa Developer Console, create a **Custom** skill named `My School Schedule`.
2. Choose **English (US)**, **Start from Scratch**, and **Alexa-hosted (Python)**.
3. Replace the generated interaction model with `interaction-model.json`.
4. Replace the generated Lambda code with `lambda_function.py`.
5. In the skill permissions, enable **Reminders** and the scope `alexa::alerts:reminders:skill:readwrite`.
6. Build the model and test in the Alexa simulator.
7. Say: `Alexa, ask my school schedule to set my school wake up.`

The skill reads only the public Pages schedule endpoint. It never receives or
stores the Gist write token.

## GitHub Actions connection

The repository workflow has an optional Alexa step. It remains a no-op until
`ALEXA_LWA_ACCESS_TOKEN` is configured as a repository secret. The token must
be an out-of-session Login with Amazon token authorized for the skill's
reminder scope. The workflow lists only reminders whose spoken text begins
with `School schedule wake-up.` and updates or removes that managed reminder.

The updater deliberately does not create a reminder when no managed reminder
exists; create the first reminder from Alexa, then configure the token. This
prevents duplicate reminders during setup.

## Safety behavior

- A stale or invalid schedule uses the default 07:15 weekday reminder.
- A confirmed no-school day removes only the managed school reminder.
- API failures return a failed workflow step without changing the Gist.
- Keep the existing iPhone 07:15 alarm until the Echo behavior has been tested.
