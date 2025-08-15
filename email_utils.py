import smtplib
from email.message import EmailMessage
from io import BytesIO

# CONFIGURACIÓN DEL REMITENTE
GMAIL_REMITENTE = "tecobot2022@gmail.com"
GMAIL_PASSWORD = "bwon lxka asxv cadg"

def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    archivo_adjunto: BytesIO = None,
    nombre_archivo: str = "archivo.xlsx",
    tipo_mime: tuple = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
):
    try:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = GMAIL_REMITENTE
        msg["To"] = destinatario
        msg.set_content(cuerpo)

        if archivo_adjunto:
            archivo_adjunto.seek(0)
            msg.add_attachment(
                archivo_adjunto.read(),
                maintype=tipo_mime[0],
                subtype=tipo_mime[1],
                filename=nombre_archivo
            )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_REMITENTE, GMAIL_PASSWORD)
            smtp.send_message(msg)

        return True

    except Exception as e:
        print(f"[ERROR al enviar correo]: {e}")
        return False
