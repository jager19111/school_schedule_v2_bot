import ssl
import socket
import hashlib

def get_fingerprint(hostname: str, port: int = 443) -> str:
    # Контекст без проверки (CERT_NONE), чтобы получить даже просроченный сертификат
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with socket.create_connection((hostname, port)) as sock:
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            der_cert = ssock.getpeercert(binary_form=True)
            return hashlib.sha256(der_cert).hexdigest()

if __name__ == "__main__":
    host = "lyceum.nstu.ru"
    print(f"SHA256 Fingerprint для {host}:")
    print(get_fingerprint(host))