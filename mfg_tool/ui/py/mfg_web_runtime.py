import os
import io
import csv
import uuid
import base64
import random
import hashlib
import struct
import binascii
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import load_pem_x509_certificate
from ecdsa.curves import NIST256p
import esp_idf_nvs_partition_gen.nvs_partition_gen as nvs_partition_gen

print("Core modules imported")

# CHIP OIDs
VENDOR_ID_OID = x509.ObjectIdentifier('1.3.6.1.4.1.37244.2.1')
PRODUCT_ID_OID = x509.ObjectIdentifier('1.3.6.1.4.1.37244.2.2')

# SPAKE2+ implementation
WS_LENGTH = NIST256p.baselen + 8

def generate_verifier(passcode, salt, iterations):
    ws = hashlib.pbkdf2_hmac('sha256', struct.pack('<I', passcode), salt, iterations, WS_LENGTH * 2)
    w0 = int.from_bytes(ws[:WS_LENGTH], byteorder='big') % NIST256p.order
    w1 = int.from_bytes(ws[WS_LENGTH:], byteorder='big') % NIST256p.order
    L = NIST256p.generator * w1
    return w0.to_bytes(NIST256p.baselen, byteorder='big') + L.to_bytes('uncompressed')

INVALID_PASSCODES = [0, 11111111, 22222222, 33333333, 44444444, 55555555, 66666666, 77777777, 88888888, 99999999, 12345678, 87654321]

# Setup payload generation
BASE38_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."

def base38_encode(value, length):
    result = []
    for _ in range(length):
        result.append(BASE38_CHARS[value % 38])
        value //= 38
    return ''.join(reversed(result))

def generate_qr_payload(vendor_id, product_id, discriminator, passcode, flow, discovery):
    version = 0
    payload_bits = 0
    payload_bits |= (version & 0x7)
    payload_bits |= (vendor_id & 0xFFFF) << 3
    payload_bits |= (product_id & 0xFFFF) << 19
    payload_bits |= (flow & 0x3) << 35
    payload_bits |= (discovery & 0xFF) << 37
    payload_bits |= (discriminator & 0xFFF) << 45
    payload_bits |= (passcode & 0x7FFFFFF) << 57
    return "MT:" + base38_encode(payload_bits, 11)

def generate_manual_code(discriminator, passcode, flow):
    d1 = (discriminator >> 10) & 0x3
    d2 = discriminator & 0x3FF
    chunk1 = (d1 << 14) | (passcode & 0x3FFF)
    chunk2 = passcode >> 14
    chunk3 = d2
    code = f"{chunk1:05d}{chunk2:04d}{chunk3:05d}"
    check = sum(int(c) for c in code) % 10
    if flow == 0:
        return f"{code[:4]}-{code[4:7]}-{code[7:11]}{check}"
    else:
        return f"{code[:4]}-{code[4:7]}-{code[7:11]}\n{code[11:]}-{check}"

# Certificate utilities
def load_cert_from_pem(pem_str):
    return load_pem_x509_certificate(pem_str.encode())

def load_key_from_pem(pem_str):
    return serialization.load_pem_private_key(pem_str.encode(), password=None)

def generate_ec_key():
    return ec.generate_private_key(ec.SECP256R1())

def cert_to_der(cert):
    return cert.public_bytes(serialization.Encoding.DER)

def cert_to_pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)

def key_to_pem(key):
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

def key_to_der(key):
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )

def key_to_raw_private(key):
    return key.private_numbers().private_value.to_bytes(32, byteorder='big')

def key_to_raw_public(key):
    pub = key.public_key().public_numbers()
    return b'\x04' + pub.x.to_bytes(32, byteorder='big') + pub.y.to_bytes(32, byteorder='big')

def compute_ski(public_key):
    """Compute Subject Key Identifier manually to avoid OpenSSL issues in Pyodide"""
    from cryptography.hazmat.primitives.hashes import SHA1, Hash
    pub_bytes = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint
    )
    digest = Hash(SHA1())
    digest.update(pub_bytes)
    return digest.finalize()

def build_certificate(vendor_id, product_id, ca_cert, ca_key, common_name, is_pai=False, lifetime=36500):
    private_key = generate_ec_key()
    public_key = private_key.public_key()
    
    x509_attrs = [
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(VENDOR_ID_OID, f"{vendor_id:04X}"),
        x509.NameAttribute(PRODUCT_ID_OID, f"{product_id:04X}"),
    ]
    subject = x509.Name(x509_attrs)
    
    now = datetime.now(timezone.utc)
    cert_builder = x509.CertificateBuilder()
    cert_builder = cert_builder.subject_name(subject)
    cert_builder = cert_builder.issuer_name(ca_cert.subject)
    cert_builder = cert_builder.public_key(public_key)
    cert_builder = cert_builder.serial_number(x509.random_serial_number())
    cert_builder = cert_builder.not_valid_before(now)
    cert_builder = cert_builder.not_valid_after(now + timedelta(days=lifetime))
    
    if is_pai:
        cert_builder = cert_builder.add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        cert_builder = cert_builder.add_extension(
            x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
    else:
        cert_builder = cert_builder.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        cert_builder = cert_builder.add_extension(
            x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
    
    # Compute SKI and AKI manually to avoid OpenSSL EC_POINT_copy issues in Pyodide
    ski = compute_ski(public_key)
    cert_builder = cert_builder.add_extension(x509.SubjectKeyIdentifier(ski), critical=False)
    
    # Get CA's SKI for AKI (or compute it)
    try:
        ca_ski_ext = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
        aki_key_id = ca_ski_ext.value.digest
    except x509.ExtensionNotFound:
        aki_key_id = compute_ski(ca_cert.public_key())
    
    cert_builder = cert_builder.add_extension(
        x509.AuthorityKeyIdentifier(
            key_identifier=aki_key_id,
            authority_cert_issuer=None,
            authority_cert_serial_number=None
        ), critical=False)
    
    signed_cert = cert_builder.sign(private_key=ca_key, algorithm=hashes.SHA256(), backend=default_backend())
    
    return signed_cert, private_key

def normalize_partition_size(size):
    """Convert partition size to hex string format expected by nvs_partition_gen"""
    if isinstance(size, str):
        size_int = int(size, 0)
    else:
        size_int = int(size)
    # Round down to multiple of 4096
    size_int = (size_int // 4096) * 4096
    if size_int < 4096:
        size_int = 0x6000
    return hex(size_int)

def generate_nvs_binary(config_csv_content, values_csv_content, partition_size=0x6000):
    """Generate NVS partition binary using esp_idf_nvs_partition_gen"""
    import tempfile
    import shutil
    
    size_str = normalize_partition_size(partition_size)
    
    temp_dir = tempfile.mkdtemp()
    try:
        config_file = os.path.join(temp_dir, 'config.csv')
        values_file = os.path.join(temp_dir, 'values.csv')
        output_file = os.path.join(temp_dir, 'partition.bin')
        
        with open(config_file, 'w') as f:
            f.write(config_csv_content)
        with open(values_file, 'w') as f:
            f.write(values_csv_content)
        
        # Create args for nvs_partition_gen - size must be hex string like '0x6000'
        args = SimpleNamespace(
            input=values_file,
            output=output_file,
            outdir=temp_dir,
            size=size_str,
            version=2,
            keygen=False,
            inputkey=None,
            keyfile=None,
            key_protect_hmac=False,
            kp_hmac_keygen=False,
            kp_hmac_keyfile=None,
            kp_hmac_inputkey=None
        )
        
        # Generate the binary
        nvs_partition_gen.generate(args)
        
        # Read the generated binary
        with open(output_file, 'rb') as f:
            return f.read()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def generate_mfg_data(config, pai_cert_pem=None, pai_key_pem=None, paa_cert_pem=None, paa_key_pem=None, cd_bytes=None):
    """Generate full manufacturing data including certificates and NVS binaries"""
    
    results = {
        'devices': [],
        'staging': {},
        'errors': []
    }
    
    vendor_id = config.get('vendor_id', 0xFFF1)
    product_id = config.get('product_id', 0x8000)
    count = config.get('count', 1)
    partition_size = config.get('size', 0x6000)
    iteration_count = config.get('iteration_count', 10000)
    commissioning_flow = config.get('commissioning_flow', 0)
    discovery_mode = config.get('discovery_mode', 2)
    enable_dynamic_passcode = config.get('enable_dynamic_passcode', False)
    cn_prefix = config.get('cn_prefix', 'ESP32')
    
    vendor_name = config.get('vendor_name', '')
    product_name = config.get('product_name', '')
    fixed_passcode = config.get('passcode')
    fixed_discriminator = config.get('discriminator')
    
    # Certificate handling
    pai_cert = None
    pai_key = None
    pai_cert_der = None
    has_certs = False
    
    if paa_cert_pem and paa_key_pem:
        # Generate PAI from PAA
        try:
            paa_cert = load_cert_from_pem(paa_cert_pem)
            paa_key = load_key_from_pem(paa_key_pem)
            pai_cn = f"{cn_prefix} PAI 00"
            pai_cert, pai_key = build_certificate(vendor_id, product_id, paa_cert, paa_key, pai_cn, is_pai=True)
            pai_cert_der = cert_to_der(pai_cert)
            results['staging']['pai_cert.pem'] = cert_to_pem(pai_cert).decode()
            results['staging']['pai_cert.der'] = {'_b64': True, 'data': base64.b64encode(pai_cert_der).decode('ascii')}
            results['staging']['pai_key.pem'] = key_to_pem(pai_key).decode()
            has_certs = True
            print(f"Generated PAI certificate: {pai_cn}")
        except Exception as e:
            results['errors'].append(f"PAA/PAI error: {str(e)}")
            
    elif pai_cert_pem and pai_key_pem:
        try:
            pai_cert = load_cert_from_pem(pai_cert_pem)
            pai_key = load_key_from_pem(pai_key_pem)
            pai_cert_der = cert_to_der(pai_cert)
            results['staging']['pai_cert.der'] = {'_b64': True, 'data': base64.b64encode(pai_cert_der).decode('ascii')}
            has_certs = True
            print("Using provided PAI certificate")
        except Exception as e:
            results['errors'].append(f"PAI load error: {str(e)}")
    
    # Build config.csv schema
    config_rows = [
        ['key', 'type', 'encoding', 'value'],
        ['chip-factory', 'namespace', '', ''],
        ['discriminator', 'data', 'u32', ''],
        ['iteration-count', 'data', 'u32', ''],
        ['salt', 'data', 'string', ''],
        ['vendor-id', 'data', 'u32', ''],
        ['product-id', 'data', 'u32', ''],
    ]
    
    if not enable_dynamic_passcode:
        config_rows.append(['verifier', 'data', 'string', ''])
    if vendor_name:
        config_rows.append(['vendor-name', 'data', 'string', ''])
    if product_name:
        config_rows.append(['product-name', 'data', 'string', ''])
    config_rows.append(['serial-num', 'data', 'string', ''])
    
    if has_certs:
        config_rows.append(['dac-cert', 'file', 'binary', ''])
        config_rows.append(['dac-key', 'file', 'binary', ''])
        config_rows.append(['dac-pub-key', 'file', 'binary', ''])
        config_rows.append(['pai-cert', 'file', 'binary', ''])
    
    if cd_bytes:
        config_rows.append(['cert-dclrn', 'file', 'binary', ''])
    
    config_csv = io.StringIO()
    writer = csv.writer(config_csv)
    writer.writerows(config_rows)
    results['staging']['config.csv'] = config_csv.getvalue()
    
    # Generate pin_disc.csv
    pin_disc_rows = []
    if enable_dynamic_passcode:
        pin_disc_rows.append(['Index', 'Iteration Count', 'Salt', 'Discriminator'])
    else:
        pin_disc_rows.append(['Index', 'PIN Code', 'Iteration Count', 'Salt', 'Verifier', 'Discriminator'])
    
    # CN/DAC tracking
    cn_dac_rows = [['CN', 'certs']]
    
    # Generate per-device data
    for i in range(count):
        device_uuid = str(uuid.uuid4())
        
        # Passcode
        if fixed_passcode:
            passcode = fixed_passcode
        else:
            passcode = random.randint(1, 99999998)
            while passcode in INVALID_PASSCODES:
                passcode = random.randint(1, 99999998)
        
        # Discriminator
        if fixed_discriminator:
            discriminator = fixed_discriminator
        else:
            discriminator = random.randint(0, 4095)
        
        # Generate salt and verifier
        salt = os.urandom(32)
        salt_b64 = base64.b64encode(salt).decode('utf-8')
        
        if not enable_dynamic_passcode:
            verifier = generate_verifier(passcode, salt, iteration_count)
            verifier_b64 = base64.b64encode(verifier).decode('utf-8')
            pin_disc_rows.append([i, passcode, iteration_count, salt_b64, verifier_b64, discriminator])
        else:
            verifier_b64 = ''
            pin_disc_rows.append([i, iteration_count, salt_b64, discriminator])
        
        # Generate QR and manual codes
        qr_payload = generate_qr_payload(vendor_id, product_id, discriminator, passcode, commissioning_flow, discovery_mode)
        manual_code = generate_manual_code(discriminator, passcode, commissioning_flow)
        
        # Serial number
        serial_num = binascii.b2a_hex(os.urandom(8)).decode('utf-8')
        
        device_data = {
            'uuid': device_uuid,
            'index': i,
            'passcode': passcode,
            'discriminator': discriminator,
            'qr_payload': qr_payload,
            'manual_code': manual_code,
            'files': {}
        }
        
        # Generate DAC if we have certificates
        if has_certs and pai_cert and pai_key:
            try:
                dac_cert, dac_key = build_certificate(vendor_id, product_id, pai_cert, pai_key, device_uuid, is_pai=False)
                
                dac_cert_pem = cert_to_pem(dac_cert)
                dac_cert_der = cert_to_der(dac_cert)
                dac_key_pem = key_to_pem(dac_key)
                dac_key_der = key_to_der(dac_key)
                dac_private_bin = key_to_raw_private(dac_key)
                dac_public_bin = key_to_raw_public(dac_key)
                
                # Store binary data with base64 encoding for JS transfer
                def encode_binary(data):
                    if isinstance(data, bytes):
                        return {'_b64': True, 'data': base64.b64encode(data).decode('ascii')}
                    return data
                
                device_data['files']['internal/DAC_cert.pem'] = dac_cert_pem.decode() if isinstance(dac_cert_pem, bytes) else dac_cert_pem
                device_data['files']['internal/DAC_cert.der'] = encode_binary(dac_cert_der)
                device_data['files']['internal/DAC_key.pem'] = dac_key_pem.decode() if isinstance(dac_key_pem, bytes) else dac_key_pem
                device_data['files']['internal/DAC_key.der'] = encode_binary(dac_key_der)
                device_data['files']['internal/DAC_private_key.bin'] = encode_binary(dac_private_bin)
                device_data['files']['internal/DAC_public_key.bin'] = encode_binary(dac_public_bin)
                device_data['files']['internal/PAI_cert.der'] = encode_binary(pai_cert_der)
                
                # Add to CN/DAC CSV
                cn_dac_rows.append([device_uuid, dac_cert_pem.decode() if isinstance(dac_cert_pem, bytes) else dac_cert_pem])
                
                print(f"Generated DAC for device {i+1}: {device_uuid}")
            except Exception as e:
                results['errors'].append(f"DAC generation error for device {i}: {str(e)}")
        
        # Build partition.csv for this device
        part_rows = [
            ['key', 'type', 'encoding', 'value'],
            ['chip-factory', 'namespace', '', ''],
            ['discriminator', 'data', 'u32', str(discriminator)],
            ['iteration-count', 'data', 'u32', str(iteration_count)],
            ['salt', 'data', 'string', salt_b64],
            ['vendor-id', 'data', 'u32', str(vendor_id)],
            ['product-id', 'data', 'u32', str(product_id)],
        ]
        
        if not enable_dynamic_passcode:
            part_rows.append(['verifier', 'data', 'string', verifier_b64])
        if vendor_name:
            part_rows.append(['vendor-name', 'data', 'string', vendor_name])
        if product_name:
            part_rows.append(['product-name', 'data', 'string', product_name])
        part_rows.append(['serial-num', 'data', 'string', serial_num])
        
        partition_csv = io.StringIO()
        writer = csv.writer(partition_csv)
        writer.writerows(part_rows)
        device_data['files']['internal/partition.csv'] = partition_csv.getvalue()
        
        # Onboarding codes CSV
        onb_csv = io.StringIO()
        writer = csv.writer(onb_csv)
        writer.writerow(['qrcode', 'manualcode', 'discriminator', 'passcode'])
        writer.writerow([qr_payload, manual_code, discriminator, passcode])
        device_data['files'][f'{device_uuid}-onb_codes.csv'] = onb_csv.getvalue()
        
        # Generate NVS partition binary
        if has_certs:
            try:
                # Build values CSV with file references (need temp files for binary generation)
                import tempfile
                temp_dir = tempfile.mkdtemp()
                
                # Write certificate files
                dac_cert_path = os.path.join(temp_dir, 'dac_cert.der')
                dac_key_path = os.path.join(temp_dir, 'dac_key.bin')
                dac_pub_path = os.path.join(temp_dir, 'dac_pub.bin')
                pai_cert_path = os.path.join(temp_dir, 'pai_cert.der')
                
                # Helper to get raw bytes from encoded data
                def get_raw_bytes(data):
                    if isinstance(data, dict) and data.get('_b64'):
                        return base64.b64decode(data['data'])
                    return data
                
                with open(dac_cert_path, 'wb') as f:
                    f.write(get_raw_bytes(device_data['files']['internal/DAC_cert.der']))
                with open(dac_key_path, 'wb') as f:
                    f.write(get_raw_bytes(device_data['files']['internal/DAC_private_key.bin']))
                with open(dac_pub_path, 'wb') as f:
                    f.write(get_raw_bytes(device_data['files']['internal/DAC_public_key.bin']))
                with open(pai_cert_path, 'wb') as f:
                    f.write(pai_cert_der)
                
                # Build full partition CSV with file paths
                full_part_rows = [
                    ['key', 'type', 'encoding', 'value'],
                    ['chip-factory', 'namespace', '', ''],
                    ['discriminator', 'data', 'u32', str(discriminator)],
                    ['iteration-count', 'data', 'u32', str(iteration_count)],
                    ['salt', 'data', 'string', salt_b64],
                    ['vendor-id', 'data', 'u32', str(vendor_id)],
                    ['product-id', 'data', 'u32', str(product_id)],
                ]
                if not enable_dynamic_passcode:
                    full_part_rows.append(['verifier', 'data', 'string', verifier_b64])
                if vendor_name:
                    full_part_rows.append(['vendor-name', 'data', 'string', vendor_name])
                if product_name:
                    full_part_rows.append(['product-name', 'data', 'string', product_name])
                full_part_rows.append(['serial-num', 'data', 'string', serial_num])
                full_part_rows.append(['dac-cert', 'file', 'binary', dac_cert_path])
                full_part_rows.append(['dac-key', 'file', 'binary', dac_key_path])
                full_part_rows.append(['dac-pub-key', 'file', 'binary', dac_pub_path])
                full_part_rows.append(['pai-cert', 'file', 'binary', pai_cert_path])
                
                # Write partition CSV
                part_csv_path = os.path.join(temp_dir, 'partition.csv')
                with open(part_csv_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerows(full_part_rows)
                
                # Generate binary
                output_bin = os.path.join(temp_dir, 'partition.bin')
                size_str = normalize_partition_size(partition_size)
                
                args = SimpleNamespace(
                    input=part_csv_path,
                    output=output_bin,
                    outdir=temp_dir,
                    size=size_str,
                    version=2,
                    keygen=False,
                    inputkey=None,
                    keyfile=None,
                    key_protect_hmac=False,
                    kp_hmac_keygen=False,
                    kp_hmac_keyfile=None,
                    kp_hmac_inputkey=None
                )
                nvs_partition_gen.generate(args)
                
                with open(output_bin, 'rb') as f:
                    bin_data = f.read()
                    # Store as base64 to preserve binary data through JS conversion
                    device_data['files'][f'{device_uuid}-partition.bin'] = {
                        '_b64': True,
                        'data': base64.b64encode(bin_data).decode('ascii')
                    }
                
                print(f"Generated partition binary for device {i+1}")
                
                # Cleanup
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                
            except Exception as e:
                results['errors'].append(f"Binary generation error for device {i}: {str(e)}")
                print(f"Binary generation error: {e}")
        
        results['devices'].append(device_data)
    
    # Write pin_disc.csv
    pin_disc_csv = io.StringIO()
    writer = csv.writer(pin_disc_csv)
    writer.writerows(pin_disc_rows)
    results['staging']['pin_disc.csv'] = pin_disc_csv.getvalue()
    
    # Write cn_dacs.csv if we have certs
    if has_certs:
        cn_dac_csv = io.StringIO()
        writer = csv.writer(cn_dac_csv)
        writer.writerows(cn_dac_rows)
        timestamp = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        results['cn_dacs_filename'] = f'cn_dacs-{timestamp}.csv'
        results['cn_dacs_content'] = cn_dac_csv.getvalue()
    
    # Write summary CSV
    summary_rows = [['UUID', 'discriminator', 'passcode', 'qrcode', 'manualcode', 'vendor-id', 'product-id', 'serial-num']]
    for d in results['devices']:
        summary_rows.append([
            d['uuid'], d['discriminator'], d['passcode'], 
            d['qr_payload'], d['manual_code'],
            hex(vendor_id), hex(product_id), ''
        ])
    
    summary_csv = io.StringIO()
    writer = csv.writer(summary_csv)
    writer.writerows(summary_rows)
    timestamp = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    results['summary_filename'] = f'summary-{timestamp}.csv'
    results['summary_content'] = summary_csv.getvalue()
    
    results['vendor_id'] = vendor_id
    results['product_id'] = product_id
    results['has_certs'] = has_certs
    
    return results

print("MFG Tool fully loaded - ready for generation")
