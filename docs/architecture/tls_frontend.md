# TLS Frontend Implementation

This document describes how the low-footprint HTTPS frontend for StunSail services is implemented.

## Overview

The StunSail system now includes a secure HTTPS frontend that:
- Provides encrypted communication using TLS 1.2+
- Forwards requests to the core service on localhost:8000
- Uses certificates generated with IP Subject Alternative Names (SANs)
- Has minimal resource usage requirements

## Implementation Details

### Certificate Generation

The certificate generation process supports IP SANs through a new script:
```bash
python3 generate_ca_and_cert.py \
    --ca-cert /etc/stunsail/certs/ca.crt \
    --ca-key /etc/stunsail/certs/ca.key \
    --server-cert /etc/stunsail/certs/server.crt \
    --server-key /etc/stunsail/certs/server.key \
    --ip-address 192.168.101.50
```

### HTTPS Frontend Service

The secure proxy is implemented as a Python aiohttp-based service that:

1. Listens on port 443 (HTTPS)
2. Forwards all requests to the core service at `localhost:8000`  
3. Uses TLS certificates for secure communication
4. Maintains minimal memory and CPU usage

### Service Configuration

The frontend runs as a systemd service named `stunsail-frontend.service`. The service file is located in:
```
/etc/systemd/system/stunsail-frontend.service
```

## Security Features

- **TLS 1.2+ only** - Enforces modern encryption standards
- **Certificate validation** - All connections must be validated against the CA 
- **Minimal attack surface** - Only exposes necessary endpoints
- **No public exposure** - Core service remains on localhost:8000

## Installation Integration

The frontend is installed as part of the standard installation process and configured to:
1. Generate certificates during setup (if they don't exist)
2. Start automatically at boot time  
3. Restart automatically if it crashes
4. Log all access and errors appropriately

This implementation provides a secure, low-resource way to expose StunSail services over HTTPS while maintaining the security of the core system components.