"""Local TLS listener sharing the exact same Flask application and camera state."""
import ipaddress
import socket
from datetime import datetime,timedelta,timezone
from pathlib import Path

from services.secure_store import atomic_write


def local_addresses():
    addresses = {'127.0.0.1','::1'}
    try:
        for item in socket.getaddrinfo(socket.gethostname(),None):
            address = ipaddress.ip_address(item[4][0].split('%')[0])
            if address.is_private and not address.is_unspecified and not address.is_link_local:
                addresses.add(str(address))
    except OSError:
        pass
    return sorted(addresses)


def ensure_certificate(directory,addresses=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    directory = Path(directory)/'tls'
    directory.mkdir(parents=True,exist_ok=True)
    cert_path,key_path = directory/'localhost.crt',directory/'localhost.key'
    addresses = addresses or local_addresses()
    names = [x509.DNSName('localhost'),x509.DNSName(socket.gethostname())]
    names += [x509.IPAddress(ipaddress.ip_address(address)) for address in addresses]
    if cert_path.exists() and key_path.exists():
        try:
            certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
            existing = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            if certificate.not_valid_after_utc > datetime.now(timezone.utc)+timedelta(days=7) and all(name in existing for name in names):
                return cert_path,key_path
        except (ValueError,x509.ExtensionNotFound):
            pass
    key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Attend local camera')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
                   .not_valid_after(now+timedelta(days=90)).add_extension(x509.SubjectAlternativeName(names),critical=False)
                   .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
                   .sign(key,hashes.SHA256()))
    atomic_write(key_path,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    atomic_write(cert_path,certificate.public_bytes(serialization.Encoding.PEM))
    return cert_path,key_path


def https_server(app,host,port):
    import ssl
    from cheroot.wsgi import Server
    from cheroot.ssl.builtin import BuiltinSSLAdapter
    certificate,key = ensure_certificate(app.config['DATA_DIR'])
    server = Server((host,port),app,numthreads=24)
    server.ssl_adapter = BuiltinSSLAdapter(str(certificate),str(key))
    server.ssl_adapter.context.minimum_version = ssl.TLSVersion.TLSv1_2
    return server
