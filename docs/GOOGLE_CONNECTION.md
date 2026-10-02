# Hosted Google connection

Hosted app: https://internshipos.vercel.app . Enable Gmail API and Google Calendar API in Google Cloud. Configure the OAuth consent screen as described below and add your Google account as a test user. Create a Web application OAuth client with this exact redirect URI:

`https://internshipos.vercel.app/api/integrations/google/callback`

Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the internshipos Vercel project production environment. Set GOOGLE_REDIRECT_URI to the hosted callback above. Add the same client ID and secret as GitHub repository secrets in varadharajanv0310/InternshipOS so the scheduled collector can refresh Google credentials. Add GOOGLE_REDIRECT_URI to the collection workflow environment with that callback when enabling hosted Google sync. Preserve the existing TOKEN_ENCRYPTION_KEY. Redeploy Vercel, then use Settings / Integrations / Connect Google in the hosted app. Never paste the client secret in chat.

The hosted collector runs every six hours; Google polling follows that schedule rather than the local 45-minute setting. The app has no Google credentials yet.

## Original local setup (local development only)

# Connect Google to the local app

The integration is implemented; no Google client or account is configured yet.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create/select an InternshipOS project.
2. Under **APIs & Services → Library**, enable **Gmail API** and **Google Calendar API**.
3. Open **Google Auth Platform**. Complete **Branding** with app name InternshipOS and your contact email. Under **Audience**, choose External for personal Gmail, keep Testing initially, and add your Gmail address as a test user.
4. Under **Data Access**, add these scopes:

   ```text
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/calendar.app.created
   ```

5. Under **Clients → Create client**, choose Web application. Add this exact **Authorized redirect URI**:

   ```text
   http://127.0.0.1:8000/api/integrations/google/callback
   ```

   The server-side flow does not need an Authorized JavaScript Origin. Create the client and retain its Client ID and Client secret.

6. In this project folder, copy `.env.example` to `.env` only if `.env` does not already exist. Edit these entries locally, preserving other values:

   ```dotenv
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/integrations/google/callback
   ```

   Keep the secret in the file rather than posting it in chat. With no configured TOKEN_ENCRYPTION_KEY, the local app creates a persistent `data/token.key`; retain it with the original database.

7. Restart from the project folder:

   ```powershell
   .\Stop-InternshipOS.ps1
   .\Start-InternshipOS.ps1
   ```

8. Open **Settings → Integrations → Connect Google**, sign in with the test-user account and review permissions. Confirm Google shows Connected after returning to the app.

Gmail access is read-only and the granted scope covers the mailbox. The app looks for recruiting messages; it does not send or delete mail. Calendar access covers app-created calendars, not your existing personal calendar. Sync defaults to 45 minutes while the backend runs. Messages need an application to match; uncertain matches wait for review.

If `redirect_uri_mismatch` appears, compare the exact redirect string: hostname, port and path must match; localhost differs from 127.0.0.1. A test-user error requires adding the signed-in address under Audience. If still Not configured, check the `.env` location and restart; existing process environment values override file values.

External apps in Testing normally have refresh tokens expire after **7 days** for these scopes, so you may need to reconnect. Long-lived operation requires addressing the project's publishing/consent settings; access can still be revoked or expire.

Sources checked 2 October 2026: [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Google token expiration](https://developers.google.com/identity/protocols/oauth2).
