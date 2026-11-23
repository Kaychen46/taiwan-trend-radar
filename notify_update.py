"""Email a report summary after GitHub Pages deployment succeeds."""

import json
import os
import smtplib
from email.message import EmailMessage


SITE_URL = "https://kaychen46.github.io/taiwan-trend-radar/"


def build_message(payload, *, sender, recipient, site_url):
    updated_at = payload["updated_at"]
    trends = payload["trends"]

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"台灣爆點雷達已更新｜{updated_at}"

    lines = [
        "台灣爆點雷達網站已成功更新。",
        f"更新時間：{updated_at}（台灣時間）",
        f"本次報告：{len(trends)} 則",
        "",
        "前 3 則話題：",
    ]
    lines.extend(f"{index}. {trend['topic_name']}" for index, trend in enumerate(trends[:3], 1))
    lines.extend(["", f"查看網站：{site_url}"])
    message.set_content("\n".join(lines))
    return message


def send_update_email(payload, *, sender, recipient, app_password, site_url=SITE_URL):
    message = build_message(payload, sender=sender, recipient=recipient, site_url=site_url)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)


def main():
    sender = os.environ["SMTP_USERNAME"]
    recipient = os.environ["NOTIFY_EMAIL"]
    app_password = os.environ["SMTP_APP_PASSWORD"]
    with open("site/data/latest_trends.json", encoding="utf-8") as report_file:
        payload = json.load(report_file)
    send_update_email(payload, sender=sender, recipient=recipient, app_password=app_password)
    print(f"Update notification sent to {recipient}")


if __name__ == "__main__":
    main()
