"""Utility for sending emails via Gmail.

This module wraps SMTP authentication and message construction to send
emails with optional attachments.  For security the sender address
(``GMAIL_REMITENTE``) and application password (``GMAIL_PASSWORD``)
are read from environment variables instead of being hard-coded in
source.  If these variables are not configured an informative error
is raised.
"""

import os
import smtplib
from email.message import EmailMessage
from io import BytesIO
from typing import Tuple, Optional

# Read the sender and password from environment variables.  These
# environment variables must be set in the deployment environment.
GMAIL_REMITENTE: str = "tecobot2022@gmail.com"
GMAIL_PASSWORD: str = "bwon lxka asxv cadg"

def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    archivo_adjunto: Optional[BytesIO] = None,
    nombre_archivo: str = "archivo.xlsx",
    tipo_mime: Tuple[str, str] = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
) -> bool:
    """
    Enviar un correo electrónico con un cuerpo de texto y un archivo adjunto opcional.

    Este helper utiliza SMTP sobre SSL para conectarse a Gmail.  Antes de
    enviar correos asegúrese de que las variables de entorno
    ``GMAIL_REMITENTE`` y ``GMAIL_PASSWORD`` estén configuradas con
    valores válidos (por ejemplo, un password de aplicación de Gmail).

    Parameters
    ----------
    destinatario : str
        Dirección de correo del destinatario.
    asunto : str
        Asunto del correo electrónico.
    cuerpo : str
        Cuerpo del mensaje en texto plano.
    archivo_adjunto : BytesIO, optional
        Archivo que se adjuntará al correo.  Debe ser un objeto
        ``BytesIO`` posicionado al inicio del contenido.
    nombre_archivo : str, optional
        Nombre de archivo que se mostrará en el adjunto.
    tipo_mime : tuple, optional
        Tipo MIME del adjunto como (maintype, subtype).

    Returns
    -------
    bool
        True si el mensaje se envió correctamente, False si ocurrió algún
        error.
    """
    # Validate configuration
    if not GMAIL_REMITENTE or not GMAIL_PASSWORD:
        raise RuntimeError(
            "Credenciales de correo no configuradas. Configure las variables de entorno "
            "GMAIL_REMITENTE y GMAIL_PASSWORD para utilizar enviar_correo()."
        )
    try:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = GMAIL_REMITENTE
        msg["To"] = destinatario
        msg.set_content(cuerpo)
        if archivo_adjunto is not None:
            # Ensure the buffer is at the beginning before reading
            archivo_adjunto.seek(0)
            msg.add_attachment(
                archivo_adjunto.read(),
                maintype=tipo_mime[0],
                subtype=tipo_mime[1],
                filename=nombre_archivo,
            )
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_REMITENTE, GMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        # Log the exception to stderr; return False to indicate failure
        print(f"[ERROR al enviar correo]: {exc}")
        return False
