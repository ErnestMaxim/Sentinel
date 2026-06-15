import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import get_settings

settings = get_settings()


def send_password_reset_email(to_email: str, token: str) -> None:
    """
    Send a password-reset email styled to match the Sentinel UI.
    Raises smtplib.SMTPException on delivery failure.
    """
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Reset your Sentinel password</title>
</head>
<body style="margin:0;padding:0;background-color:#080a0f;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#080a0f;padding:48px 16px 64px;">
    <tr>
      <td align="center">
        <table width="520" cellpadding="0" cellspacing="0" border="0"
               style="max-width:520px;width:100%;
                      background-color:#0d1117;
                      border-radius:20px;
                      border:1px solid rgba(255,255,255,0.10);
                      box-shadow:0 24px 80px rgba(0,0,0,0.7);">
          <tr>
            <td style="padding:40px 44px 36px;">
              <p style="margin:0 0 10px;font-size:26px;font-weight:700;
                         color:#f4f7ff;letter-spacing:-0.4px;line-height:1.2;
                         font-family:'Segoe UI',Arial,sans-serif;">
                Reset your password
              </p>
              <p style="margin:0 0 30px;font-size:14px;color:#8993b0;line-height:1.65;
                         font-family:'Segoe UI',Arial,sans-serif;">
                You requested a password reset for your Sentinel account.
                This link expires in&nbsp;<strong style="color:#f4f7ff;font-weight:600;">1&nbsp;hour</strong>.
              </p>
              <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:30px;">
                <tr>
                  <td style="border-radius:12px;">
                    <a href="{reset_url}"
                       style="display:inline-block;padding:14px 40px;
                              font-size:15px;font-weight:700;color:#131723;
                              background-color:#f4f6fb;text-decoration:none;
                              border-radius:12px;font-family:'Segoe UI',Arial,sans-serif;">
                      Reset password
                    </a>
                  </td>
                </tr>
              </table>
              <div style="height:1px;background:rgba(255,255,255,0.08);margin-bottom:26px;"></div>
              <p style="margin:0 0 18px;font-size:13px;color:#8993b0;line-height:1.6;
                         font-family:'Segoe UI',Arial,sans-serif;">
                If you didn't request this, you can safely ignore this email —
                your password will not change.
              </p>
              <p style="margin:0 0 5px;font-size:12px;color:#5a6380;
                         font-family:'Segoe UI',Arial,sans-serif;">
                Or copy this link:
              </p>
              <p style="margin:0;word-break:break-all;">
                <a href="{reset_url}"
                   style="font-size:12px;color:#c9961a;text-decoration:underline;
                          font-family:'Segoe UI',Arial,sans-serif;">
                  {reset_url}
                </a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 44px 26px;border-top:1px solid rgba(255,255,255,0.06);">
              <p style="margin:0;font-size:12px;color:#3d4560;
                         font-family:'Segoe UI',Arial,sans-serif;">
                © 2025 Sentinel — Anti-plagiarism platform
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Reset your Sentinel password\n\n"
        f"Visit this link (expires in 1 hour):\n{reset_url}\n\n"
        f"If you didn't request this, ignore this email.\n\n"
        f"© 2025 Sentinel"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your Sentinel password"
    msg["From"]    = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to_email, msg.as_string())