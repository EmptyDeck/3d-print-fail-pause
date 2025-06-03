import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage


def send_alert_email(image_path, timestamp):
    # Put you email here
    naver_user = 'emailhere@naver.com'
    # Password here
    naver_password = 'passwordhere!'
    # To. email here
    to_email = 'reciverhere@naver.com'
    # You are all set
    subject = 'Urgent! 3D printer fail detected'
    html_body = f"""
    <html>
      <body>
        <h2>3D Printer Failure Detected</h2>
        <p>Failure detected at {timestamp}</p>
        <p><img src="cid:alert_image"></p>
      </body>
    </html>
    """

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = naver_user
    msg["To"] = to_email

    msg.attach(MIMEText(html_body, "html", _charset="utf-8"))

    with open(image_path, 'rb') as img_file:
        img = MIMEImage(img_file.read(), name='alert_image.jpg')
        img.add_header('Content-ID', '<alert_image>')
        msg.attach(img)

    try:
        with smtplib.SMTP_SSL('smtp.naver.com', 465) as server:
            server.login(naver_user, naver_password)
            server.sendmail(naver_user, to_email, msg.as_string())
        print('Alert email sent successfully!')
    except Exception as e:
        print('Failed to send alert email:', e)
